"""
Deep Research Worker - 工蜂智能体
负责簇内页面的深度分析和处理
"""

import asyncio
import time
from typing import List, Dict, Any, Optional, Coroutine
from loguru import logger

from .base import BaseAgent, BatchProcessor
from core.models import (
    ResearchComplexityConfig,
    PageAnalysis,
    TopicCluster,
    RESEARCH_COMPLEXITY_CONFIGS,
    PageAnalysisResponse,
    ClusterSynthesisResponse
)


class OptimizedWorker(BaseAgent):
    """
    优化的Worker智能体
    
    职责：
    1. 批量页面内容提取
    2. 结构化页面分析
    3. 重要性评分
    4. 簇级综合摘要
    """
    
    def __init__(self, worker_id: str, complexity_config: ResearchComplexityConfig, research_purpose: str = ""):
        super().__init__(agent_id=worker_id)
        self.complexity_config = complexity_config
        self.research_purpose = research_purpose
        self.batch_processor = BatchProcessor(max_concurrent=3)  # 每个Worker内部最多3个并发页面

    """
    Worker主函数
    """
    async def process_cluster(
        self, 
        cluster_pages: List[Dict[str, Any]], 
        cluster_theme: str,
        max_pages: int = 10
    ) -> str:
        """
        处理单个簇的所有页面，返回简洁的文本摘要
        """
        try:
            start_time = time.time()
            logger.info(f"Worker {self.agent_id} 开始处理簇: {cluster_theme}, {len(cluster_pages)} 个页面")
            
            # 1. 批量获取页面内容
            page_contents = await self.batch_fetch_page_contents(cluster_pages)
            
            # 2. 并发页面分析，获取简短摘要列表
            page_summaries = await self.batch_analyze_pages(page_contents, cluster_theme)
            
            # 3. 直接拼接所有页面摘要
            cluster_summary = f"主题簇：{cluster_theme}\n\n"
            cluster_summary += "\n\n".join(page_summaries)
            
            elapsed = time.time() - start_time
            logger.info(f"Worker {self.agent_id} 完成处理，耗时: {elapsed:.2f}s")
            
            return cluster_summary
            
        except Exception as e:
            logger.error(f"Worker {self.agent_id} 处理失败: {e}")
            # 返回降级结果
            return f"主题簇：{cluster_theme}\n\nWorker {self.agent_id} 处理失败：{str(e)}\n请手动查看相关页面获取详细信息。"
    
    async def batch_fetch_page_contents(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量获取页面内容
        """
        try:
            logger.debug(f"Worker {self.agent_id} 开始获取 {len(pages)} 个页面内容")
            
            async def fetch_single_page(page_meta: Dict[str, Any]) -> Dict[str, Any]:
                try:
                    # 获取页面内容（包含文档文件）
                    content, timestamp = await self.notion_client.get_page_content(
                        page_meta["notion_id"],
                        include_files=True,
                        max_length=8000  # 根据复杂度配置调整
                    )
                    
                    return {
                        **page_meta,
                        "content": content,
                        "actual_timestamp": timestamp,
                        "last_edited_time": timestamp,  # 添加时间信息
                        "word_count": len(content)
                    }
                    
                except Exception as e:
                    logger.warning(f"获取页面内容失败 {page_meta['notion_id']}: {e}")
                    return {
                        **page_meta,
                        "content": f"内容获取失败: {str(e)}",
                        "actual_timestamp": page_meta.get("last_edited_time", ""),
                        "last_edited_time": page_meta.get("last_edited_time", ""),  # 添加时间信息
                        "word_count": 0
                    }
            
            # 并发获取所有页面内容
            results = await self.batch_processor.process_batch(
                pages, fetch_single_page
            )
            
            # 过滤有效结果
            valid_pages = [r for r in results if not r.get("error")]
            logger.info(f"Worker {self.agent_id} 成功获取 {len(valid_pages)}/{len(pages)} 个页面内容")
            
            return valid_pages
            
        except Exception as e:
            logger.error(f"批量获取页面内容失败: {e}")
            return []
    
    async def batch_analyze_pages(
        self, 
        page_contents: List[Dict[str, Any]], 
        cluster_theme: str
    ) -> List[str]:
        """
        批量分析页面内容，返回简短文本摘要列表
        （后期可以优化）
        """
        try:
            logger.debug(f"Worker {self.agent_id} 开始分析 {len(page_contents)} 个页面")
            
            async def analyze_single_page(page_data: Dict[str, Any]) -> str:
                try:
                    # 根据复杂度配置确定摘要长度
                    target_length = self.complexity_config.target_summary_length
                    min_length = max(150, int(target_length * 0.6))
                    max_length = int(target_length * 1.2)  # 允许20%的弹性
                    
                    # 创建基于复杂度的页面分析prompt
                    analysis_prompt = f"""
                    你将作为研究助理，对以下页面进行深入分析，用于“Context Engineering”（上下文工程）中信息密度最优的摘要构建。

                    **请生成一段{self.complexity_config.summary_style}风格的分析性摘要，长度控制在{min_length}-{target_length}字之间。**

                    ---

                    🧾 页面信息：
                    - 标题：{page_data["title"]}
                    - 所属主题（Cluster Theme）：{cluster_theme}
                    - 当前研究目的：{self.research_purpose}
                    - 分析模式（Complexity Mode）：{self.complexity_config.complexity_type}

                    📄 页面内容：
                    {page_data["content"][:10000]}
                    ---

                    🎯 分析要求：
                    - 结合“研究目的”进行结构化理解，不要仅仅复述原文。
                    - 聚焦以下关键分析维度：
                    {chr(10).join([f"• {area}" for area in self.complexity_config.focus_areas])}
                    - 避免空洞总结、空话套话；优先提取有推理价值的句子或模式。
                    - 可使用列点或段落式写作方式，便于嵌入语言模型上下文。

                    📌 输出格式：
                    - 仅返回纯文本摘要，无需其他说明或格式标记。
                    """
                    
                    # 调用简单文本API
                    summary_text = await self.call_gemini_simple(analysis_prompt)
                    
                    # 根据复杂度配置控制摘要长度
                    if len(summary_text) > max_length:
                        summary_text = summary_text[:target_length] + "..."
                    
                    # 格式化输出：标题 + 时间 + 摘要
                    last_edited = page_data.get('last_edited_time', page_data.get('actual_timestamp', ''))
                    formatted_time = last_edited[:10] if last_edited else '未知时间'  # 只取日期部分
                    
                    return f"**{page_data['title']}** ({formatted_time})\n{summary_text}"
                    
                except Exception as e:
                    logger.warning(f"页面分析失败 {page_data['title']}: {e}")
                    last_edited = page_data.get('last_edited_time', page_data.get('actual_timestamp', ''))
                    formatted_time = last_edited[:10] if last_edited else '未知时间'
                    return f"**{page_data['title']}** ({formatted_time})\n页面分析失败，需要手动查看。"
            
            # 并发分析所有页面
            results = await self.batch_processor.process_batch(
                page_contents, analyze_single_page
            )
            
            # 过滤有效结果
            valid_summaries = [r for r in results if isinstance(r, str) and not (isinstance(r, dict) and r.get("error"))]
            # logger.info(f"Worker {self.agent_id} 成功分析 {len(valid_summaries)}/{len(page_contents)} 个页面")
            
            return valid_summaries
            
        except Exception as e:
            logger.error(f"批量页面分析失败: {e}")
            return [f"Worker {self.agent_id} 批量分析失败"]
    
    def create_basic_page_analysis(self, page_data: Dict[str, Any]) -> PageAnalysis:
        """创建基础页面分析（降级策略）"""
        
        # 简单的内容分析
        content = page_data.get("content", "")
        content_preview = content[:200] + "..." if len(content) > 200 else content
        
        return PageAnalysis(
            notion_id=page_data["notion_id"],
            title=page_data["title"],
            content=content,
            summary=f"页面 '{page_data['title']}' 的基础摘要。{content_preview}",
            key_points=[
                f"页面标题：{page_data['title']}",
                f"内容长度：{page_data.get('word_count', 0)} 字符",
                f"标签：{', '.join(page_data.get('tags', []))}",
                "详细分析失败，需要手动查看"
            ],
            importance_score=0.5,
            relevance_score=0.3,  # 降级时给较低的关联度
            word_count=page_data.get("word_count", 0),
            supporting_quotes=[],
            research_value={
                "theoretical_contribution": "未评估",
                "practical_application": "可参考页面内容",
                "citation_worthiness": "中等"
            }
        )



    """
    subagent 分簇功能未来待扩展 暂未使用
    """
    def filter_and_rank_pages(
        self, 
        page_analyses: List[PageAnalysis], 
        max_pages: int,
        relevance_threshold: float = 0.2
    ) -> List[PageAnalysis]:
        """
        过滤和排序页面：基于关联度过滤 + 重要性排序
        """
        try:
            if not page_analyses:
                return []
            
            # 1. 关联度过滤：移除低关联度页面
            relevant_pages = [
                page for page in page_analyses 
                if page.relevance_score >= relevance_threshold
            ]
            
            # logger.info(f"Worker {self.agent_id} 关联度过滤：{len(relevant_pages)}/{len(page_analyses)} 个页面通过 (阈值: {relevance_threshold})")
            
            # 如果过滤后页面太少，降低阈值
            if len(relevant_pages) < 2 and page_analyses:
                logger.warning(f"Worker {self.agent_id} 关联页面过少，降低阈值到 0.1")
                relevant_pages = [
                    page for page in page_analyses 
                    if page.relevance_score >= 0.1
                ]
            
            # 如果还是太少，至少保留评分最高的几个
            if len(relevant_pages) < 1 and page_analyses:
                logger.warning(f"Worker {self.agent_id} 强制保留评分最高的页面")
                relevant_pages = sorted(page_analyses, key=lambda x: x.relevance_score, reverse=True)[:2]
            
            # 2. 综合评分排序：关联度权重60% + 重要性权重40%
            def combined_score(page: PageAnalysis) -> float:
                return page.relevance_score * 0.6 + page.importance_score * 0.4
            
            sorted_pages = sorted(relevant_pages, key=combined_score, reverse=True)
            
            # 3. 选择top页面
            min_pages_per_cluster = min(2, len(sorted_pages))
            target_pages = max(min_pages_per_cluster, min(max_pages // 3, len(sorted_pages)))
            
            filtered_pages = sorted_pages[:target_pages]
            
            logger.info(f"Worker {self.agent_id} 最终筛选：{len(filtered_pages)} 个页面，"
                        f"平均关联度: {sum(p.relevance_score for p in filtered_pages)/len(filtered_pages):.2f}")
            return filtered_pages
            
        except Exception as e:
            logger.error(f"页面过滤排序失败: {e}")
            return page_analyses[:3]  # 返回前3个作为降级
    
    def _parse_text_analysis(self, text_response: str) -> Dict[str, Any]:
        """从文本响应中解析页面分析信息"""
        try:
            # 简单的文本解析逻辑
            lines = text_response.split('\n')
            
            summary = ""
            key_points = []
            supporting_quotes = []
            
            current_section = None
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                if "摘要" in line or "总结" in line:
                    current_section = "summary"
                elif "要点" in line or "关键点" in line:
                    current_section = "key_points"
                elif "引用" in line or "证据" in line:
                    current_section = "quotes"
                elif line.startswith('-') or line.startswith('•') or line.startswith('1.'):
                    if current_section == "key_points":
                        key_points.append(line.lstrip('- •1234567890.').strip())
                    elif current_section == "quotes":
                        supporting_quotes.append(line.lstrip('- •1234567890.').strip())
                else:
                    if current_section == "summary":
                        summary += line + " "
            
            # 如果没有找到结构化内容，使用前200字符作为摘要
            if not summary:
                summary = text_response[:200] + "..." if len(text_response) > 200 else text_response
            
            if not key_points:
                key_points = ["AI分析结果", "详细内容请查看原始响应"]
            
            return {
                "summary": summary.strip(),
                "key_points": key_points,
                "importance_score": 0.6,  # 默认中等重要性
                "relevance_score": 0.5,   # 默认中等关联度
                "supporting_quotes": supporting_quotes,
                "research_value": {
                    "theoretical_contribution": "基于文本分析",
                    "practical_application": "可供参考",
                    "citation_worthiness": "中等"
                }
            }
            
        except Exception as e:
            logger.warning(f"文本解析失败: {e}")
            return {
                "summary": f"文本解析结果：{text_response[:300]}...",
                "key_points": ["解析失败，使用原始文本"],
                "importance_score": 0.4,
                "relevance_score": 0.4,
                "supporting_quotes": [],
                "research_value": {
                    "theoretical_contribution": "未知",
                    "practical_application": "需要人工分析",
                    "citation_worthiness": "低"
                }
            }
    
    async def synthesize_cluster(
        self, 
        page_analyses: List[PageAnalysis], 
        cluster_theme: str
    ) -> Dict[str, Any]:
        """
        生成簇级综合摘要
        """
        try:
            if not page_analyses:
                return {
                    "synthesis": f"簇 {cluster_theme} 没有有效的页面分析结果。",
                    "quotes": [],
                    "cross_references": []
                }
            
            # 准备簇摘要数据
            cluster_data = {
                "theme": cluster_theme,
                "page_count": len(page_analyses),
                "pages_summary": [
                    {
                        "title": page.title,
                        "summary": page.summary,
                        "importance_score": page.importance_score,
                        "key_points": page.key_points[:3]  # 限制要点数量
                    }
                    for page in page_analyses
                ],
                "complexity": self.complexity_config.complexity_type
            }
            
            # 创建簇综合prompt
            synthesis_prompt = self._create_cluster_synthesis_prompt(cluster_data)
            
            # 调用Gemini进行综合
            synthesis_result = await self.call_gemini_structured(synthesis_prompt)
            
            # 尝试从结构化结果或文本响应中提取信息
            if "cluster_synthesis" in synthesis_result:
                cluster_synthesis = synthesis_result["cluster_synthesis"]
            elif "text_response" in synthesis_result:
                # 如果是文本响应，直接使用
                cluster_synthesis = {"synthesis": synthesis_result["text_response"]}
            else:
                cluster_synthesis = synthesis_result
            
            # 收集代表性引用
            all_quotes = []
            for page in page_analyses:
                all_quotes.extend(page.supporting_quotes)
            
            # 选择最佳引用
            representative_quotes = all_quotes[:3] if all_quotes else []
            
            return {
                "synthesis": cluster_synthesis.get("synthesis", self._create_basic_synthesis(page_analyses, cluster_theme)),
                "quotes": representative_quotes,
                "cross_references": cluster_synthesis.get("cross_references", [])
            }
            
        except Exception as e:
            logger.error(f"簇综合失败: {e}")
            return {
                "synthesis": self._create_basic_synthesis(page_analyses, cluster_theme),
                "quotes": [],
                "cross_references": []
            }
    
    def _create_cluster_synthesis_prompt(self, cluster_data: Dict[str, Any]) -> str:
        """创建簇综合prompt"""
        
        pages_info = "\n".join([
            f"- {page['title']}: {page['summary'][:200]}..."
            for page in cluster_data["pages_summary"]
        ])
        
        return f"""{self.prompts.STABLE_SYSTEM_PREFIX}

            {self.prompts.COMPLEXITY_TEMPLATES[cluster_data['complexity']]}
            
            **当前任务**：簇级综合摘要生成
            
            **输入信息**：
            簇主题：{cluster_data['theme']}
            页面数量：{cluster_data['page_count']}
            页面信息：
            {pages_info}
            
            **综合要求**：
            根据当前分析模式，生成结构化的簇综合摘要：
            
            ```json
            {{
                "cluster_synthesis": {{
                    "synthesis": "基于{cluster_data['complexity']}模式的400-600字簇综合分析，整合所有页面的核心观点",
                    "key_themes": ["主题1", "主题2", "主题3"],
                    "cross_references": ["与其他主题的关联说明"],
                    "methodology_insights": "从页面中提炼的方法论见解"
                }}
            }}
            ```
            
            请开始综合分析："""

    def _create_basic_synthesis(self, page_analyses: List[PageAnalysis], cluster_theme: str) -> str:
        """创建基础综合摘要（降级策略）"""
        
        if not page_analyses:
            return f"簇 '{cluster_theme}' 暂无有效页面分析结果。"
        
        # 统计信息
        total_pages = len(page_analyses)
        avg_importance = sum(p.importance_score for p in page_analyses) / total_pages
        
        # 收集关键要点
        all_key_points = []
        for page in page_analyses:
            all_key_points.extend(page.key_points)
        
        # 生成基础摘要
        synthesis = f"""主题簇 '{cluster_theme}' 包含 {total_pages} 个页面的分析结果。

核心特征：
- 平均重要性评分：{avg_importance:.2f}
- 主要页面：{', '.join([p.title for p in page_analyses[:3]])}
- 关键洞察：基于页面内容分析，此簇涵盖了相关领域的重要信息

主要贡献：
1. 提供了结构化的知识整理
2. 包含了实用的参考信息
3. 为后续研究提供了基础资料

建议进一步查看具体页面内容以获得更深入的理解。"""

        return synthesis
    
    async def create_fallback_cluster(
        self, 
        cluster_pages: List[Dict[str, Any]], 
        cluster_theme: str
    ) -> TopicCluster:
        """创建降级簇结果"""
        
        # 创建基础页面分析
        fallback_analyses = []
        for page in cluster_pages[:3]:  # 只处理前3个页面
            basic_analysis = PageAnalysis(
                notion_id=page["notion_id"],
                title=page["title"],
                content="内容获取失败",
                summary=f"页面 {page['title']} 的基础信息（Worker处理失败）",
                key_points=[
                    f"页面标题：{page['title']}",
                    f"页面标签：{', '.join(page.get('tags', []))}",
                    "需要手动查看详细内容"
                ],
                importance_score=0.4,
                relevance_score=0.3,  # 添加missing字段
                word_count=0,
                supporting_quotes=[],
                research_value={
                    "theoretical_contribution": "未评估",
                    "practical_application": "未评估", 
                    "citation_worthiness": "低"
                }
            )
            fallback_analyses.append(basic_analysis)
        
        return TopicCluster(
            cluster_id=self.agent_id,
            theme=f"{cluster_theme}（降级处理）",
            pages=fallback_analyses,
            cluster_synthesis=f"Worker {self.agent_id} 处理失败，返回基础结果。建议手动查看相关页面以获取完整信息。包含 {len(cluster_pages)} 个页面的基础元数据。",
            representative_quotes=[],
            cross_references=[]
        )

    async def process(self, *args, **kwargs) -> str:
        """BaseAgent要求实现的抽象方法"""
        return await self.process_cluster(*args, **kwargs)