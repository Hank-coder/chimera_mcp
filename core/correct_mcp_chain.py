"""
正确的MCP LangChain编排
MCP Client输入 → Gemini意图识别 → Graphiti查询Neo4j → LLM选择最佳路径 → Notion内容获取 → 输出
"""

import asyncio
import json
from typing import List, Dict, Any, Optional
from loguru import logger

from langchain.schema.runnable import RunnableLambda
from langchain.schema.runnable.base import RunnableSequence
from langchain.schema import BaseOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate

from .models import (
    IntentSearchRequest,
    IntentSearchResponse,
    IntentSearchMetadata,
    ConfidencePath,
    CorePageResult,
    RelatedPageResult,
    ConfidencePathMetadata
)
from .graphiti_client import GraphitiClient
from .notion_client import NotionExtractor
from config.settings import get_settings


class IntentKeywordsParser(BaseOutputParser[List[str]]):
    """意图关键词解析器"""
    
    def parse(self, text: str) -> List[str]:
        try:
            if '{' in text and '}' in text:
                start_idx = text.find('{')
                end_idx = text.rfind('}') + 1
                json_str = text[start_idx:end_idx]
                data = json.loads(json_str)
                return data.get('intent_keywords', [])
        except:
            pass
        
        # 备选解析
        return [word.strip() for word in text.split() if len(word.strip()) > 1][:5]


class PathSelectionParser(BaseOutputParser[int]):
    """路径选择解析器"""
    
    def parse(self, text: str) -> int:
        try:
            if '{' in text and '}' in text:
                start_idx = text.find('{')
                end_idx = text.rfind('}') + 1
                json_str = text[start_idx:end_idx]
                data = json.loads(json_str)
                return data.get('selected_path_index', 1) - 1  # 转为0索引
        except:
            pass
        return 0  # 默认选择第一个


class CorrectMCPChain:
    """
    正确的MCP流程链
    Gemini意图识别 → Graphiti查询 → LLM路径选择 → Notion内容获取
    """
    
    def __init__(self, graph_client: GraphitiClient, notion_client: NotionExtractor):
        self.graph_client = graph_client
        self.notion_client = notion_client
        self.settings = get_settings()
        
        # 初始化Gemini模型
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=self.settings.gemini_api_key,
            temperature=0.1,
            max_output_tokens=2000
        )
        
        # 解析器
        self.intent_parser = IntentKeywordsParser()
        self.path_parser = PathSelectionParser()
        
        # 构建LangChain链
        self.mcp_chain = self._build_mcp_chain()
    
    def _build_mcp_chain(self) -> RunnableSequence:
        """构建MCP处理链"""
        
        # Step 1: Gemini意图识别链
        intent_prompt = PromptTemplate(
            input_variables=["user_query"],
            template="""作为智能意图识别专家，从用户查询中提取关键的意图识别词汇。

用户查询: "{user_query}"

请分析查询内容，提取出最能代表用户搜索意图的关键词。
考虑因素：
1. 核心概念和主题
2. 具体的名词和专业术语
3. 行动意图相关词汇

请返回JSON格式：
{{
    "intent_keywords": ["关键词1", "关键词2", "关键词3"],
    "reasoning": "简短分析"
}}

限制：最多提取5个关键词。"""
        )
        
        intent_chain = RunnableSequence(
            intent_prompt,
            self.llm,
            self.intent_parser,
            RunnableLambda(self._prepare_graphiti_query)
        )
        
        # Step 2: Graphiti查询链
        graphiti_chain = RunnableLambda(self._graphiti_query_paths)
        
        # Step 3: LLM路径选择链
        path_selection_prompt = PromptTemplate(
            input_variables=["user_query", "intent_keywords", "paths_info"],
            template="""作为智能路径选择专家，从候选路径中选择最符合用户查询意图的一条。

用户查询: "{user_query}"
意图关键词: {intent_keywords}

候选路径:
{paths_info}

请分析每条路径与用户查询的匹配程度，考虑：
1. 页面标题的相关性
2. 关系结构的合理性  
3. 内容覆盖的完整性
4. 系统置信度评分

请返回JSON格式：
{{
    "selected_path_index": 1,
    "reasoning": "选择理由"
}}

注意：selected_path_index是路径编号（1-N）"""
        )
        
        path_selection_chain = RunnableSequence(
            RunnableLambda(self._build_path_selection_input),
            path_selection_prompt,
            self.llm,
            self.path_parser,
            RunnableLambda(self._select_best_path)
        )
        
        # Step 4: Notion内容获取链
        content_chain = RunnableLambda(self._fetch_notion_content)
        
        # Step 5: 结果格式化链
        format_chain = RunnableLambda(self._format_final_response)
        
        # 组合完整链
        return RunnableSequence(
            intent_chain,
            graphiti_chain,
            path_selection_chain,
            content_chain,
            format_chain
        )
    
    async def process_mcp_request(self, user_query: str, client_id: str = "mcp_client") -> IntentSearchResponse:
        """处理MCP请求"""
        logger.info(f"📡 Processing MCP request: {user_query}")
        
        try:
            result = await self.mcp_chain.ainvoke({
                "user_query": user_query,
                "client_id": client_id,
                "graph_client": self.graph_client,
                "notion_client": self.notion_client
            })
            
            return result
            
        except Exception as e:
            logger.exception(f"MCP chain failed: {e}")
            return IntentSearchResponse(
                success=False,
                intent_keywords=[],
                confidence_paths=[],
                total_results=0,
                error=str(e)
            )
    
    def _prepare_graphiti_query(self, intent_keywords: List[str]) -> Dict[str, Any]:
        """准备Graphiti查询参数"""
        return {
            "intent_keywords": intent_keywords,
            "graph_client": self.graph_client,
            "notion_client": self.notion_client
        }
    
    async def _graphiti_query_paths(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """使用Graphiti查询Neo4j路径"""
        intent_keywords = inputs["intent_keywords"]
        graph_client = inputs["graph_client"]
        
        logger.info(f"🔍 Graphiti查询关键词: {intent_keywords}")
        
        # 存储所有路径结果
        all_paths = []
        
        for keyword in intent_keywords:
            try:
                # 使用Graphiti搜索
                search_results = await graph_client.search_by_query(keyword, limit=10)
                
                # 为每个搜索结果构建路径
                for result in search_results:
                    # 从该页面开始扩展路径
                    expanded_pages = await graph_client.expand_from_pages(
                        page_ids=[result.notion_id],
                        depth=2,
                        relation_types=None  # 使用所有关系类型
                    )
                    
                    # 构建路径数据
                    path = {
                        "path_id": f"path_{result.notion_id}",
                        "core_page": {
                            "notion_id": result.notion_id,
                            "title": result.title,
                            "url": result.url,
                            "tags": result.tags,
                            "relevance_score": result.relevance_score
                        },
                        "related_pages": [
                            {
                                "notion_id": exp.page_id,
                                "title": exp.title,
                                "url": exp.url,
                                "depth": exp.depth,
                                "relationship_path": exp.path,
                                "tags": exp.tags
                            }
                            for exp in expanded_pages
                        ],
                        "total_pages": 1 + len(expanded_pages),
                        "keyword_match": keyword,
                        "confidence_score": result.relevance_score
                    }
                    
                    all_paths.append(path)
                    
            except Exception as e:
                logger.warning(f"Graphiti查询关键词 '{keyword}' 失败: {e}")
        
        # 去重并按置信度排序
        unique_paths = {}
        for path in all_paths:
            path_id = path["path_id"]
            if path_id not in unique_paths or path["confidence_score"] > unique_paths[path_id]["confidence_score"]:
                unique_paths[path_id] = path
        
        sorted_paths = sorted(unique_paths.values(), key=lambda x: x["confidence_score"], reverse=True)[:5]
        
        logger.info(f"📊 Graphiti返回 {len(sorted_paths)} 条优质路径")
        
        return {
            **inputs,
            "paths": sorted_paths
        }
    
    def _build_path_selection_input(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """构建路径选择输入"""
        user_query = inputs.get("user_query", "")
        intent_keywords = inputs.get("intent_keywords", [])
        paths = inputs.get("paths", [])
        
        # 格式化路径信息
        paths_info = ""
        for i, path in enumerate(paths, 1):
            related_titles = [p["title"] for p in path["related_pages"][:3]]  # 只显示前3个
            paths_info += f"""
路径 {i}: {path["path_id"]}
- 核心页面: {path["core_page"]["title"]}
- 相关页面: {", ".join(related_titles)}{"..." if len(path["related_pages"]) > 3 else ""}
- 总页面数: {path["total_pages"]}
- 系统置信度: {path["confidence_score"]:.2f}
- 匹配关键词: {path["keyword_match"]}
"""
        
        return {
            "user_query": user_query,
            "intent_keywords": ", ".join(intent_keywords),
            "paths_info": paths_info.strip(),
            "paths": paths
        }
    
    def _select_best_path(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """选择最佳路径"""
        paths = inputs.get("paths", [])
        selected_index = inputs  # 这里inputs实际是parser返回的index
        
        if isinstance(selected_index, dict):
            selected_index = 0  # 备选
        
        if 0 <= selected_index < len(paths):
            selected_path = paths[selected_index]
            logger.info(f"🏆 LLM选择路径: {selected_path['path_id']}")
        else:
            selected_path = paths[0] if paths else None
            logger.warning(f"LLM选择无效，使用第一个路径")
        
        return {
            **inputs,
            "selected_path": selected_path
        }
    
    async def _fetch_notion_content(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """获取Notion内容"""
        selected_path = inputs.get("selected_path")
        notion_client = inputs.get("notion_client")
        
        if not selected_path:
            return {**inputs, "content": None}
        
        logger.info(f"📚 获取路径内容: {selected_path['path_id']}")
        
        # 收集所有页面ID
        all_page_ids = [selected_path["core_page"]["notion_id"]]
        all_page_ids.extend([p["notion_id"] for p in selected_path["related_pages"]])
        
        try:
            # 批量获取页面内容
            page_contents = await notion_client.get_pages_content_batch(all_page_ids)
            
            # 构建内容结果
            content_result = {
                "core_page": {
                    **selected_path["core_page"],
                    "content": page_contents.get(selected_path["core_page"]["notion_id"], "")
                },
                "related_pages": []
            }
            
            for related in selected_path["related_pages"]:
                content_result["related_pages"].append({
                    **related,
                    "content": page_contents.get(related["notion_id"], "")
                })
            
            logger.info(f"✅ 成功获取 {len(all_page_ids)} 个页面内容")
            
            return {
                **inputs,
                "content": content_result
            }
            
        except Exception as e:
            logger.error(f"获取Notion内容失败: {e}")
            return {**inputs, "content": None}
    
    def _format_final_response(self, inputs: Dict[str, Any]) -> IntentSearchResponse:
        """格式化最终响应"""
        user_query = inputs.get("user_query", "")
        client_id = inputs.get("client_id", "mcp_client")
        intent_keywords = inputs.get("intent_keywords", [])
        paths = inputs.get("paths", [])
        content = inputs.get("content")
        
        if not content:
            return IntentSearchResponse(
                success=False,
                intent_keywords=intent_keywords,
                confidence_paths=[],
                total_results=0,
                error="未能获取内容"
            )
        
        # 构建ConfidencePath
        core_page_result = CorePageResult(
            notion_id=content["core_page"]["notion_id"],
            title=content["core_page"]["title"],
            url=content["core_page"]["url"],
            tags=content["core_page"]["tags"],
            content=content["core_page"]["content"],
            confidence_score=content["core_page"]["relevance_score"]
        )
        
        related_page_results = []
        for related in content["related_pages"]:
            related_page_results.append(RelatedPageResult(
                page_id=related["notion_id"],
                title=related["title"],
                url=related["url"],
                content=related["content"],
                depth=related["depth"],
                relationship_path=related["relationship_path"]
            ))
        
        confidence_path = ConfidencePath(
            core_page=core_page_result,
            related_pages=related_page_results,
            path_metadata=ConfidencePathMetadata(
                total_pages=1 + len(related_page_results),
                confidence_level="high" if content["core_page"]["relevance_score"] >= 0.8 else "medium",
                expansion_depth=2
            )
        )
        
        return IntentSearchResponse(
            success=True,
            intent_keywords=intent_keywords,
            confidence_paths=[confidence_path],
            total_results=1,
            search_metadata=IntentSearchMetadata(
                initial_candidates=len(paths),
                high_confidence_matches=1,
                confidence_threshold=0.7
            )
        )


# 全局实例
_correct_mcp_chain = None

def get_correct_mcp_chain(graph_client: GraphitiClient, notion_client: NotionExtractor) -> CorrectMCPChain:
    """获取正确的MCP链实例"""
    global _correct_mcp_chain
    if _correct_mcp_chain is None:
        _correct_mcp_chain = CorrectMCPChain(graph_client, notion_client)
    return _correct_mcp_chain