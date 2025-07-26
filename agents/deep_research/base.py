"""
Deep Research基础架构
包含共享的基础类、工具函数和常量定义
"""

import asyncio
import time
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from loguru import logger
import google.generativeai as genai
from asyncio_throttle import Throttler

from core.models import (
    DeepResearchRequest, 
    ResearchComplexityConfig,
    RESEARCH_COMPLEXITY_CONFIGS,
    PageAnalysis,
    TopicCluster,
    ResearchContext
)
from core.graphiti_client import GraphitiClient
from core.notion_client import NotionClient
from prompts.cache_optimized_prompts import CacheOptimizedPrompts
from config.settings import settings


class BaseAgent(ABC):
    """Deep Research系统基础智能体"""
    
    def __init__(self, agent_id: str = "base_agent"):
        self.agent_id = agent_id
        self.throttler = Throttler(rate_limit=8)  # 每秒8个API调用
        self.api_call_count = 0
        self.processing_time = 0.0
        
        # 初始化客户端
        self.graphiti_client = GraphitiClient()
        self.notion_client = NotionClient()
        self.prompts = CacheOptimizedPrompts()
        
        # 配置Gemini
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.gemini_model = genai.GenerativeModel(settings.GEMINI_MODEL)
        #
        # logger.info(f"Initialized {self.__class__.__name__} with ID: {agent_id}")
    
    @abstractmethod
    async def process(self, *args, **kwargs) -> Any:
        """子类必须实现的核心处理方法"""
        pass
    
    async def call_gemini_simple(self, prompt: str) -> str:
        """
        调用Gemini API并返回简单文本响应
        不强制JSON格式，更加稳定
        """
        try:
            async with self.throttler:
                self.api_call_count += 1
                start_time = time.time()
                
                response = await asyncio.to_thread(
                    self.gemini_model.generate_content,
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=3000
                    )
                )
                
                elapsed = time.time() - start_time
                self.processing_time += elapsed
                
                if not response or not response.text:
                    raise ValueError("Gemini返回空响应")
                
                # logger.debug(f"Gemini API调用成功，耗时: {elapsed:.2f}s")
                return response.text.strip()
                
        except Exception as e:
            logger.error(f"Gemini API调用失败: {e}")
            raise
    
    async def _call_gemini_json(self, prompt: str) -> str:
        """
        调用Gemini API并强制返回JSON格式
        """
        try:
            async with self.throttler:
                self.api_call_count += 1
                start_time = time.time()
                
                response = await asyncio.to_thread(
                    self.gemini_model.generate_content,
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        response_mime_type="application/json"  # 强制JSON格式
                    )
                )
                
                elapsed = time.time() - start_time
                self.processing_time += elapsed
                
                if not response or not response.text:
                    raise Exception("Gemini返回空响应")
                    
                return response.text
                
        except Exception as e:
            logger.error(f"Gemini JSON API调用失败: {e}")
            raise
    
    async def call_gemini_structured(self, prompt: str, response_schema: Any = None) -> Dict[str, Any]:
        """
        调用Gemini API并尝试返回结构化响应
        如果JSON解析失败，返回包含原始文本的字典
        """
        try:
            # 调用Gemini并强制JSON格式
            text_response = await self._call_gemini_json(prompt)
            
            # 尝试解析为JSON
            import json
            import re
            try:
                # 清理响应文本
                clean_text = text_response.strip()
                
                # 移除可能的markdown格式
                if clean_text.startswith('```json'):
                    clean_text = re.sub(r'^```json\s*\n?', '', clean_text)
                    clean_text = re.sub(r'\n?```$', '', clean_text)
                elif clean_text.startswith('```'):
                    clean_text = re.sub(r'^```\s*\n?', '', clean_text)
                    clean_text = re.sub(r'\n?```$', '', clean_text)
                
                # 额外清理：移除开头的换行和空格，确保以 { 开始
                clean_text = clean_text.strip()
                if not clean_text.startswith('{') and '{' in clean_text:
                    # 找到第一个 { 的位置并从那里开始
                    start_pos = clean_text.find('{')
                    clean_text = clean_text[start_pos:]
                
                # 确保以 } 结束
                if not clean_text.endswith('}') and '}' in clean_text:
                    # 找到最后一个 } 的位置并截止到那里
                    end_pos = clean_text.rfind('}')
                    clean_text = clean_text[:end_pos + 1]
                
                # 尝试解析JSON
                result = json.loads(clean_text)
                return result
                
            except json.JSONDecodeError:
                # JSON解析失败，返回包含原始文本的结构
                logger.warning(f"JSON解析失败，返回原始文本")
                return {"text_response": text_response}
                
        except Exception as e:
            logger.error(f"Gemini API调用失败: {e}")
            raise
    
    async def validate_page_structure(self, page_id: str) -> Dict[str, Any]:
        """
        验证页面结构：检查页面是否存在且有子节点
        """
        try:
            # 检查页面是否存在
            page_info = await self.notion_client.get_page_basic_info(page_id)
            if not page_info:
                return {
                    "valid": False,
                    "error": "页面不存在或无权限访问"
                }
            
            # 检查是否有子页面（通过图数据库）
            if not self.graphiti_client._initialized:
                await self.graphiti_client.initialize()
            
            async with self.graphiti_client._driver.session() as session:
                query = """
                MATCH (root:NotionPage {notionId: $page_id})<-[:CHILD_OF]-(child:NotionPage)
                RETURN count(child) as child_count,
                       collect(child.title)[0..5] as sample_titles
                """
                
                result = await session.run(query, page_id=page_id)
                record = await result.single()
                
                child_count = record["child_count"] if record else 0
                sample_titles = record["sample_titles"] if record else []
                
                if child_count == 0:
                    return {
                        "valid": False,
                        "error": "页面没有子节点，无法进行深度研究"
                    }
                
                return {
                    "valid": True,
                    "page_title": page_info.get("title", "Unknown"),
                    "child_count": child_count,
                    "sample_child_titles": sample_titles,
                    "estimated_scope": "small" if child_count < 10 else "medium" if child_count < 30 else "large"
                }
                
        except Exception as e:
            logger.error(f"页面结构验证失败: {e}")
            return {
                "valid": False,
                "error": f"验证过程出错: {str(e)}"
            }
    
    async def traverse_subgraph_bfs(self, root_page_id: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """
        BFS遍历子图，返回页面元信息用于后续分析
        """
        try:
            if not self.graphiti_client._initialized:
                await self.graphiti_client.initialize()
            
            async with self.graphiti_client._driver.session() as session:
                query = f"""
                MATCH path = (root:NotionPage {{notionId: $root_id}})-[:CHILD_OF*0..{max_depth}]-(page:NotionPage)
                WHERE length(path) <= {max_depth}
                RETURN DISTINCT 
                    page.notionId as page_id,
                    page.title as title,
                    page.tags as tags,
                    page.level as level,
                    page.lastEditedTime as last_edited,
                    page.url as url,
                    length(path) as distance_from_root
                ORDER BY distance_from_root ASC, page.level DESC
                LIMIT 200
                """
                
                result = await session.run(query, root_id=root_page_id)
                
                pages = []
                async for record in result:
                    pages.append({
                        "notion_id": record["page_id"],
                        "title": record["title"] or "Untitled",
                        "tags": record["tags"] or [],
                        "level": record["level"] or 0,
                        "last_edited_time": record["last_edited"],
                        "url": record["url"] or "",
                        "distance_from_root": record["distance_from_root"]
                    })
                
                logger.info(f"BFS遍历完成，找到 {len(pages)} 个页面")
                return pages
                
        except Exception as e:
            logger.error(f"BFS遍历失败: {e}")
            return []
    
    def create_balanced_batches(self, items: List[Any], num_batches: int) -> List[List[Any]]:
        """创建负载均衡的批次"""
        if not items:
            return [[] for _ in range(num_batches)]
        
        # 简单的轮询分配
        batches = [[] for _ in range(num_batches)]
        for i, item in enumerate(items):
            batches[i % num_batches].append(item)
        
        return batches
    
    def get_complexity_config(self, complexity: str) -> ResearchComplexityConfig:
        """获取复杂度配置"""
        return RESEARCH_COMPLEXITY_CONFIGS.get(complexity, RESEARCH_COMPLEXITY_CONFIGS["standard"])
    
    async def create_fallback_result(self, failed_data: Any, context: str = "unknown") -> Dict[str, Any]:
        """创建降级结果"""
        logger.warning(f"创建降级结果 for context: {context}")
        return {
            "status": "fallback",
            "context": context,
            "data": failed_data,
            "message": "处理失败，使用降级结果"
        }


class BatchProcessor:
    """批处理工具类"""
    
    def __init__(self, max_concurrent: int = 6):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_batch(self, items: List[Any], processor_func, *args, **kwargs) -> List[Any]:
        """并发处理批次，带错误隔离"""
        
        async def process_single(item):
            async with self.semaphore:
                try:
                    return await processor_func(item, *args, **kwargs)
                except Exception as e:
                    logger.error(f"批处理单项失败: {e}")
                    return {"error": str(e), "item": item}
        
        tasks = [process_single(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"批处理项 {i} 异常: {result}")
                processed_results.append({"error": str(result), "index": i})
            else:
                processed_results.append(result)
        
        return processed_results


# 工具函数
def calculate_optimal_clusters(page_count: int, max_workers: int = 6) -> int:
    """计算最优簇数量"""
    if page_count <= 10:
        return min(3, max_workers)
    elif page_count <= 30:
        return min(4, max_workers)
    elif page_count <= 60:
        return min(5, max_workers)
    else:
        return max_workers


def estimate_processing_time(page_count: int, complexity: str) -> float:
    """估算处理时间（秒）"""
    base_time = {
        "overview": 2.0,
        "standard": 3.0,
        "detailed": 4.5,
        "comprehensive": 6.0
    }.get(complexity, 3.0)
    
    # 基于页面数量的线性增长
    page_factor = 0.2 * page_count
    
    return base_time + page_factor


def format_processing_metadata(agent: BaseAgent, page_count: int, complexity: str) -> Dict[str, Any]:
    """格式化处理元数据"""
    return {
        "agent_id": agent.agent_id,
        "api_calls_used": agent.api_call_count,
        "processing_time_seconds": round(agent.processing_time, 2),
        "pages_processed": page_count,
        "complexity_level": complexity,
        "timestamp": time.time()
    }