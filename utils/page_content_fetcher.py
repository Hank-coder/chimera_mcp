#!/usr/bin/env python3
"""
统一的Notion页面内容获取器
整合表格、文档、图片等多种内容类型的处理
用于Deep Research、Intent Search等模块
"""

from typing import Dict, Any, Optional, Tuple, List
from loguru import logger
from core.notion_client import NotionClient
from core.file_extractor import FileContentExtractor


class PageContentFetcher:
    """
    统一的页面内容获取器
    
    功能：
    1. 获取Notion页面的完整内容（包括表格、子块等）
    2. 提取并处理附件文档（PDF、Word、Excel等）
    3. 处理图片和其他媒体内容
    4. 支持内容长度限制和截断策略
    5. 统一的错误处理和降级策略
    """
    
    def __init__(self, notion_client: Optional[NotionClient] = None):
        """初始化页面内容获取器"""
        self.notion_client = notion_client or NotionClient()
        self.file_extractor = FileContentExtractor()
        
        # 默认配置
        self.default_config = {
            'include_files': True,          # 是否包含文档文件
            'include_tables': True,         # 是否包含表格内容
            'include_linked_pages': False,  # 是否包含链接页面（通常不需要）
            'max_content_length': 8000,     # 最大内容长度
            'max_file_content': 6000,       # 单个文件最大内容长度
            'table_format': 'markdown',     # 表格格式: 'markdown' | 'plain'
            'truncate_strategy': 'smart'    # 截断策略: 'smart' | 'simple'
        }
    
    async def get_page_content(
        self,
        page_id: str,
        config: Optional[Dict[str, Any]] = None,
        purpose: str = ""
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        获取页面的完整内容
        
        Args:
            page_id: Notion页面ID
            config: 配置选项，会与默认配置合并
            purpose: 用途说明，用于优化内容提取策略
            
        Returns:
            Tuple[content, timestamp, metadata]
            - content: 页面完整内容
            - timestamp: 最后编辑时间
            - metadata: 元数据信息（包含统计、文件列表等）
        """
        try:
            # 合并配置
            final_config = {**self.default_config, **(config or {})}
            
            logger.debug(f"开始获取页面内容: {page_id}, purpose: {purpose}")
            
            # 获取基础页面内容 - 使用NotionExtractor的方法
            normalized_id = self.notion_client._normalize_page_id(page_id)
            
            # 获取页面基本信息（包含时间戳）
            page_info = await self.notion_client.extractor.get_page_basic_info(normalized_id)
            timestamp = page_info.get('last_edited_time', '') if page_info else ''
            
            # 根据配置获取页面内容
            if final_config['include_files']:
                # 自动解析文件 处理 PDF WORD EXCEL
                content = await self.notion_client.extractor.get_page_content_with_files(normalized_id)
            else:
                content = await self.notion_client.extractor.get_page_content(normalized_id)
            
            # 处理内容为空的情况
            if not content or not content.strip():
                page_title = page_info.get('title', 'Unknown') if page_info else 'Unknown'
                content = f"页面 '{page_title}' 没有内容, 作为路径参考。"
            else:
                content = content.strip()
            
            # 构建元数据
            metadata = {
                'page_id': page_id,
                'timestamp': timestamp,
                'content_length': len(content) if content else 0,
                'has_tables': self._detect_tables(content) if content else False,
                'has_files': self._detect_files(content) if content else False,
                'config_used': final_config,
                'purpose': purpose
            }
            
            # 内容后处理
            if content:
                content = self._post_process_content(content, final_config, metadata)
            
            logger.debug(f"页面内容获取完成: {len(content) if content else 0} 字符")
            
            return content or "", timestamp or "", metadata
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"获取页面内容失败 {page_id}: {e}")
            
            # 处理常见错误情况
            if "Could not find block with ID" in error_msg:
                error_content = f"无法访问页面 {page_id}: 页面不存在或未授权访问。请确保：\n1. 页面ID正确\n2. 页面已与Notion integration分享\n3. 检查页面权限设置"
            elif "Make sure the relevant pages and databases are shared" in error_msg:
                error_content = f"权限错误: 页面 {page_id} 未与integration分享。请在Notion中将此页面分享给你的integration。"
            else:
                error_content = f"无法获取页面内容: {error_msg}"
            
            return error_content, "", {
                'page_id': page_id,
                'error': str(e),
                'content_length': len(error_content),
                'has_tables': False,
                'has_files': False
            }
    
    async def get_multiple_pages_content(
        self,
        page_ids: List[str],
        config: Optional[Dict[str, Any]] = None,
        purpose: str = ""
    ) -> List[Dict[str, Any]]:
        """
        批量获取多个页面的内容
        
        Args:
            page_ids: 页面ID列表
            config: 配置选项
            purpose: 用途说明
            
        Returns:
            List of page content dictionaries
        """
        try:
            import asyncio
            
            # 创建并发任务
            tasks = []
            for page_id in page_ids:
                task = self._get_single_page_with_error_handling(page_id, config, purpose)
                tasks.append(task)
            
            # 并发执行
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"页面 {page_ids[i]} 获取失败: {result}")
                    processed_results.append({
                        'page_id': page_ids[i],
                        'content': "",
                        'timestamp': "",
                        'metadata': {'error': str(result)},
                        'success': False
                    })
                else:
                    processed_results.append({
                        'page_id': page_ids[i],
                        'content': result[0],
                        'timestamp': result[1],
                        'metadata': result[2],
                        'success': True
                    })
            
            return processed_results
            
        except Exception as e:
            logger.error(f"批量获取页面内容失败: {e}")
            return []
    
    async def _get_single_page_with_error_handling(
        self,
        page_id: str,
        config: Optional[Dict[str, Any]],
        purpose: str
    ) -> Tuple[str, str, Dict[str, Any]]:
        """带错误处理的单页面获取"""
        try:
            return await self.get_page_content(page_id, config, purpose)
        except Exception as e:
            logger.warning(f"页面 {page_id} 内容获取失败: {e}")
            return "", "", {'error': str(e)}
    
    def _post_process_content(
        self,
        content: str,
        config: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> str:
        """内容后处理"""
        try:
            # 表格格式化
            if config.get('table_format') == 'markdown' and metadata.get('has_tables'):
                content = self._format_tables_as_markdown(content)
            
            # 智能截断
            if config.get('truncate_strategy') == 'smart' and len(content) > config['max_content_length']:
                content = self._smart_truncate(content, config['max_content_length'])
            
            # 内容清理
            content = self._clean_content(content)
            
            return content
            
        except Exception as e:
            logger.warning(f"内容后处理失败: {e}")
            return content
    
    def _detect_tables(self, content: str) -> bool:
        """检测内容中是否包含表格"""
        table_indicators = [
            "--- 表格 ---",
            " | ",
            "\n|",
            "table_row",
            "[Table with"
        ]
        return any(indicator in content for indicator in table_indicators)
    
    def _detect_files(self, content: str) -> bool:
        """检测内容中是否包含文件"""
        file_indicators = [
            "[PDF文档]",
            "[Word文档]",
            "[Excel文档]",
            "[文档内容]",
            "文件名："
        ]
        return any(indicator in content for indicator in file_indicators)
    
    def _format_tables_as_markdown(self, content: str) -> str:
        """将表格格式化为Markdown格式"""
        try:
            # 这里可以添加更复杂的表格格式化逻辑
            # 目前保持简单实现
            return content
        except Exception as e:
            logger.warning(f"表格格式化失败: {e}")
            return content
    
    def _smart_truncate(self, content: str, max_length: int) -> str:
        """智能截断：优先保留完整的段落和表格"""
        try:
            if len(content) <= max_length:
                return content
            
            # 尝试在段落边界截断
            truncated = content[:max_length]
            
            # 查找最后一个段落边界
            last_paragraph = truncated.rfind('\n\n')
            if last_paragraph > max_length * 0.7:  # 如果截断位置合理
                truncated = truncated[:last_paragraph]
            
            # 查找最后一个完整句子
            last_sentence = truncated.rfind('。')
            if last_sentence > max_length * 0.8:  # 如果截断位置合理
                truncated = truncated[:last_sentence + 1]
            
            return truncated + "\n\n... (内容已截断，显示前部分)"
            
        except Exception as e:
            logger.warning(f"智能截断失败: {e}")
            return content[:max_length] + "..."
    
    def _clean_content(self, content: str) -> str:
        """清理内容：去除多余空白、格式化等"""
        try:
            # 去除多余的空行
            lines = content.split('\n')
            cleaned_lines = []
            prev_empty = False
            
            for line in lines:
                line = line.strip()
                if not line:
                    if not prev_empty:
                        cleaned_lines.append('')
                    prev_empty = True
                else:
                    cleaned_lines.append(line)
                    prev_empty = False
            
            return '\n'.join(cleaned_lines).strip()
            
        except Exception as e:
            logger.warning(f"内容清理失败: {e}")
            return content


# 便利函数
async def get_page_content_for_deep_research(
    page_id: str,
    complexity: str = "standard",
    max_length: int = 7000
) -> Tuple[str, str, Dict[str, Any]]:
    """
    为Deep Research优化的页面内容获取
    """
    fetcher = PageContentFetcher()
    config = {
        'include_files': True,
        'include_tables': True,
        'max_content_length': max_length,
        'truncate_strategy': 'smart',
        'table_format': 'markdown'
    }
    
    return await fetcher.get_page_content(
        page_id=page_id,
        config=config,
        purpose=f"deep_research_{complexity}"
    )


async def get_page_content_for_intent_search(
    page_id: str,
    is_core_page: bool = True,
    max_length: int = 8000
) -> Tuple[str, str, Dict[str, Any]]:
    """
    为Intent Search优化的页面内容获取
    """
    fetcher = PageContentFetcher()
    config = {
        'include_files': True,
        'include_tables': True,
        'max_content_length': max_length if is_core_page else 6000,
        'truncate_strategy': 'smart',
        'table_format': 'plain'  # Intent Search可能更适合纯文本
    }
    
    return await fetcher.get_page_content(
        page_id=page_id,
        config=config,
        purpose=f"intent_search_{'core' if is_core_page else 'related'}"
    )


# 全局实例（可选）
_global_fetcher = None

def get_global_page_fetcher() -> PageContentFetcher:
    """获取全局页面内容获取器实例"""
    global _global_fetcher
    if _global_fetcher is None:
        _global_fetcher = PageContentFetcher()
    return _global_fetcher