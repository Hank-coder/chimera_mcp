#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chimera FastMCP Server - HTTP MCP服务器
基于FastMCP框架的可流式传输HTTP MCP服务器，支持意图搜索和知识检索
兼容mcp-remote客户端
"""
import os
import subprocess
import sys
import argparse
from pathlib import Path
from typing import Dict, Any, List
from fastmcp import FastMCP, Context
from pydantic import BaseModel, Field
from loguru import logger

# 确保项目根目录在Python路径中
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.intent_search import search_user_intent, IntentSearchEngine
from agents.deep_research import ContextEngineeringDirector
from utils.fastmcp_utils import get_bearer_token
from config.settings import get_settings
from agents.relationship_search import search_wechat_relationships
from agents.personal_memory_writer import write_personal_memory
from core.models import (
    DeepResearchRequest,
    SearchToolInput,
    SearchToolResponse,
    SearchResultItem,
    FetchToolInput,
    FetchToolResponse,
    FetchResultItem,
    PersonalMemoryInput,
    PersonalMemoryResponse
)
import json


# Pydantic模型定义
class IntentSearchInput(BaseModel):
    """意图搜索输入模型（用于从 Notion 中搜索语义相关内容）"""

    query: str = Field(
        ...,
        description=(
            "用户意图识别后的关键词或短语，用于发起搜索。"
            "应先从原始自然语言问题中提取核心意图，例如："
            "'我记得我写过碳中和计划' → '碳中和 计划'"
        )
    )

    search_results: int = Field(
        3,
        description=(
            "返回的搜索结果数量，默认返回 3 条相关路径。"
            "可根据需要调整数量上限。"
        )
    )

    speed: bool = Field(
        True,
        description=(
            "速度模式开关。"
            "True: 仅使用embedding搜索，速度快但准确性较低。"
            "False: 使用混合搜索（LLM+embedding），准确性高但速度较慢。"
        )
    )

    max_file_content_length: int = Field(
        8000,
        description=(
            "单个文档文件内容的最大字符数限制。默认8000字符适合大多数LLM。"
            "根据您的LLM上下文窗口调整：大模型可用更大值(12000+)，小模型建议6000以下。"
        )
    )

    max_page_content_length: int = Field(
        10000,
        description=(
            "单个Notion页面内容的最大字符数限制。默认10000字符，防止prompt过长。"
            "可根据LLM能力调整：大模型可设置16000+。"
        )
    )

class RelationshipSearchInput(BaseModel):
    """关系搜索输入模型（用于从微信关系图谱中搜索社交关系）"""
    
    query: str = Field(
        ...,
        description=(
            "用户查询的关系问题，例如："
            "'肥猫在GREEN研发项目里是什么角色？'"
            "'张三和李四是什么关系？'"
            "'谁认识yvnn？'"
        )
    )
    
    max_results: int = Field(
        5,
        description=(
            "返回的最大搜索结果数量，默认返回5个相关结果。"
            "可根据需要调整数量上限。"
        )
    )

class DeepResearchInput(BaseModel):
    """深度研究输入模型（用于生成大模型研究上下文）"""
    
    page_id: str = Field(..., description="根页面Notion ID")
    
    purpose: str = Field(
        ...,
        description=(
            "研究目的和关注点。例如：\n"
            "- '了解机器学习项目的实施方法'\n"
            "- '分析产品设计的核心原则'\n"
            "- '总结团队管理的最佳实践'\n"
            "- '研究技术架构的演进思路'"
        )
    )
    
    max_pages: int = Field(
        default=10,
        ge=5,
        le=20,
        description=(
            "返回的最大页面数量（5-20）。建议：\n"
            "- 快速概览：5-8页\n"
            "- 标准研究：10-12页\n" 
            "- 深度分析：15-20页"
        )
    )
    
    research_complexity: str = Field(
        default="standard",
        description=(
            "研究复杂度，决定分析深度和总结风格：\n"
            "- overview: 高层概览，突出核心结论和趋势\n"
            "- standard: 平衡分析，核心观点+支撑证据\n" 
            "- detailed: 深度分析，包含方法论和案例\n"
            "- comprehensive: 学术级分析，完整理论框架"
        )
    )

class ChimeraResult(BaseModel):
    """通用结果模型"""
    success: bool = Field(..., description="操作是否成功")
    data: Dict[str, Any] = Field(..., description="结果数据")
    message: str = Field("", description="结果消息")


class ChimeraFastMCPServer:
    """Chimera FastMCP HTTP服务器主类"""
    
    def __init__(self):
        # 启用无状态HTTP模式，兼容mcp-remote
        self.mcp = FastMCP("chimera-memory")
        self.notion_client = None
        self.settings = get_settings()
        self._setup_tools()
    
    def _validate_auth(self, ctx):
        """简单的Bearer认证验证"""
        if not self.settings.enable_auth or not self.settings.chimera_api_key:
            return True
            
        try:
            client_token = get_bearer_token(ctx)
            if client_token == self.settings.chimera_api_key:
                logger.debug("Bearer认证成功")
                return True
            else:
                logger.warning(f"Bearer认证失败：token不匹配")
                return False
        except Exception as e:
            logger.warning(f"Bearer认证失败：{str(e)}")
            return False

    def _parse_page_ids(self, page_id_str: str) -> List[str]:
        """
        解析page_id字符串为ID列表

        支持三种格式：
        1. 单个ID: 'page-id-1'
        2. 逗号分隔: 'page-id-1,page-id-2,page-id-3'
        3. JSON数组: '["page-id-1", "page-id-2"]'
        """
        try:
            page_id_str = page_id_str.strip()

            # 情况1: JSON数组格式
            if page_id_str.startswith('[') and page_id_str.endswith(']'):
                try:
                    page_ids = json.loads(page_id_str)
                    if isinstance(page_ids, list):
                        return [str(pid).strip() for pid in page_ids if pid]
                except json.JSONDecodeError:
                    pass

            # 情况2: 逗号分隔格式
            if ',' in page_id_str:
                return [pid.strip() for pid in page_id_str.split(',') if pid.strip()]

            # 情况3: 单个ID
            return [page_id_str] if page_id_str else []

        except Exception as e:
            logger.error(f"解析page_id失败: {e}")
            return []

    def _setup_tools(self):
        """设置MCP工具"""

        @self.mcp.tool(
            title="个人知识库搜索（Notion）",
            description=(
                    "这是我（陈宇函）的个人知识库 **Chimera** —— 简单 / 标准搜索工具。"
                    "用于从第二大脑（Notion）中查找相关笔记、记录、项目、总结等内容。\n\n"
                    "**调用参数**（字段名区分大小写，必须严格对应）：\n"
                    "- query (字符串，必填)：搜索短语或关键词（中英文均可），用于 Embedding 相似度搜索\n"
                    "- search_results (整数, 可选, 默认=5)：返回的最大搜索结果条数 最大为10\n"
                    "- speed (布尔值)：搜索模式开关\n"
                    "  - false：[默认] 使用 LLM 判断 + embedding 搜索的混合策略，准确性高（准）\n\n"
                    "  - true：仅 embedding 搜索（速度快）\n"    
                    "**性能建议**：\n"
                    "- 默认使用速度模式\n"
                    "- 需要高准确性时使用标准模式"
            )
        )
        async def intent_search(params: IntentSearchInput, ctx: Context) -> ChimeraResult:
            """
            智能意图搜索工具
            params: IntentSearchInput 是业务输入参数，由客户端/大模型传入；
            ctx: Context 是上下文参数，由 MCP 框架自动注入。

            """
            try:
                # 认证检查
                if not self._validate_auth(ctx):
                    return ChimeraResult(
                        success=False,
                        data={"paths": []},
                        message="Authentication failed"
                    )
                
                logger.debug(f"Intent search request: {params.query}")
                
                result = await search_user_intent(
                    user_input=params.query,
                    max_results=params.search_results,
                    speed=params.speed
                )
                
                logger.debug(f"Intent search completed, success: {result.success}")
                
                # 处理搜索结果，提取路径内容（参考demo_intent_search.py）
                if result.success and result.confidence_paths:
                    paths_data = []
                    
                    for confidence_path in result.confidence_paths:
                        core_page = confidence_path.core_page

                        # 🚀 优化：直接使用已有的页面内容，避免重复获取
                        # CorePageResult 中已经包含了页面内容，无需重复调用 get_path_contents_async

                        # 构建路径内容：使用已获取的页面内容
                        path_contents = []

                        # 如果有完整路径信息，构建路径内容数组
                        if core_page.path_ids and core_page.path_titles:
                            # 为路径中的每个页面创建内容项，核心页面使用已获取的内容
                            for i, (page_id, page_title) in enumerate(zip(core_page.path_ids, core_page.path_titles)):
                                if page_id == core_page.notion_id:
                                    # 这是核心页面，使用已获取的内容
                                    page_content_item = {
                                        "position": i,
                                        "title": page_title,
                                        "notion_id": page_id,
                                        "content": core_page.content,
                                        "content_length": len(core_page.content),
                                        "last_edited_time": core_page.last_edited_time,
                                        "status": "success"
                                    }
                                else:
                                    # 这是路径中的其他页面，创建基本信息（不重复获取内容）
                                    page_content_item = {
                                        "position": i,
                                        "title": page_title,
                                        "notion_id": page_id,
                                        "content": f"📄 路径页面: {page_title}",
                                        "content_length": 0,
                                        "last_edited_time": "",
                                        "status": "path_only"
                                    }
                                path_contents.append(page_content_item)
                        else:
                            # 没有完整路径信息，只有核心页面
                            path_contents = [{
                                "position": 0,
                                "title": core_page.title,
                                "notion_id": core_page.notion_id,
                                "content": core_page.content,
                                "content_length": len(core_page.content),
                                "last_edited_time": core_page.last_edited_time,
                                "status": "success"
                            }]

                        path_data = {
                            "path": core_page.path_string,
                            "confidence": core_page.confidence_score,
                            "last_edited_time": core_page.last_edited_time,
                            "path_contents": path_contents,
                            "total_pages": len(path_contents)
                        }
                        
                        paths_data.append(path_data)
                    
                    return ChimeraResult(
                        success=True,
                        data={
                            "paths": paths_data,
                            "search_summary": f"找到 {len(paths_data)} 条相关路径",
                            "intent_keywords": result.intent_keywords
                        },
                        message=f"找到 {len(paths_data)} 个相关结果"
                    )
                
                else:
                    return ChimeraResult(
                        success=False,
                        data={
                            "paths": [],
                            "search_summary": "未找到匹配结果",
                            "error": result.error
                        },
                        message="未找到相关结果"
                    )
                
            except Exception as e:
                logger.exception(f"Error in intent_search: {e}")
                return ChimeraResult(
                    success=False,
                    data={"paths": [], "search_summary": "搜索过程中发生错误"},
                    message=f"搜索失败: {str(e)}"
                )
        
        @self.mcp.tool(
            title="关系与记忆搜索（统一图谱）",
            description=(
                "这是我 *ゞ肥の猫ゞ* **（陈宇函）的个人知识图谱搜索工具，"
                "统一检索微信社交关系和个人记忆，用于查找人际关系、项目参与、个人偏好等信息。\n\n"
           
                "**示例查询**：\n"
                "{\n"
                "  \"query\": \"Chimera项目开发\",\n"
                "  \"max_results\": 3\n"
                "}\n\n"
            )
        )
        async def relationship_search(params: RelationshipSearchInput, ctx: Context) -> ChimeraResult:
            """
            微信关系搜索工具
            params: RelationshipSearchInput 是业务输入参数，由客户端/大模型传入；
            ctx: Context 是上下文参数，由 MCP 框架自动注入。
            """
            try:
                # 认证检查
                if not self._validate_auth(ctx):
                    return ChimeraResult(
                        success=False,
                        data={"relationships": []},
                        message="Authentication failed"
                    )
                
                logger.debug(f"Relationship search request: {params.query}")
                
                # 调用微信关系搜索
                result = await search_wechat_relationships(
                    query=params.query,
                    max_results=params.max_results
                )
                
                logger.debug(f"Relationship search completed, success: {result.success}")
                
                if result.success:
                    return ChimeraResult(
                        success=True,
                        data={
                            "relationships": result.episodes,
                            "formatted_answer": result.formatted_answer,
                            "query_analysis": result.query_analysis.model_dump() if result.query_analysis else None,
                            "processing_time_ms": result.processing_time_ms
                        },
                        message=f"找到 {len(result.episodes)} 个相关关系"
                    )
                else:
                    return ChimeraResult(
                        success=False,
                        data={
                            "relationships": [],
                            "formatted_answer": "未找到相关关系信息",
                            "error": result.error
                        },
                        message="未找到相关关系"
                    )
                
            except Exception as e:
                logger.exception(f"Error in relationship_search: {e}")
                return ChimeraResult(
                    success=False,
                    data={"relationships": [], "formatted_answer": "搜索过程中发生错误"},
                    message=f"关系搜索失败: {str(e)}"
                )
        
        @self.mcp.tool(
            title="文档深度搜索（Notion）",
            description=(
                    "这是我（陈宇函）的Notion个人知识库**深度搜索**工具,侧重于多文档，为研究RAG Context Engineering打造!\n\n"
                    "**触发条件**：当用户问题包含Notion PageID 以及“深度” “仔细”（深度研究 深度介绍 仔细研究）等相关关键词时调用此工具！\n\n"
                    "**核心功能**：\n"
                    "1. 自动验证页面结构（检查子页面层级≤4）。\n"
                    "2. 智能语义分簇（4个Worker并行分析页面内容）。\n"
                    "3. 生成研究级结构化上下文（适用于Context Engineering）。\n\n"
                    "**参数说明**：\n"
                    "- `page_id` (str): 研究起点页面ID（Notion页面UUID）。\n"
                    "- `purpose` (str): 研究目的和关注重点，决定聚合逻辑。\n"
                    "- `max_pages` (int): 处理的页面数量（根据需要选择 5-20）。\n"
                    "- `research_complexity` (str): 研究复杂度，控制分析深度与风格,"
                    "可选：overview|standard|detailed|comprehensive"

                    "**🧪 示例**：\n"
                    "用户提出请求：`请对「page_id」这个页面做一次深度知识提炼，用于后续代码生成支持。`\n\n"
                    "调用方式：\n"
                    "```json\n"
                    "{\n"
                    "  \"page_id\": \"「page_id」\",\n"
                    "  \"purpose\": \"提取结构化 Agent 规划模式供模型调用\",\n"
                    "  \"max_pages\": 10,\n"
                    "  \"research_complexity\": \"detailed\"\n"
                    "}\n"
                    "```"
            )
        )
        async def deep_research(params: DeepResearchInput, ctx: Context) -> ChimeraResult:
            """
            智能深度研究工具
            params: DeepResearchInput 是业务输入参数，由客户端/大模型传入；
            ctx: Context 是上下文参数，由 MCP 框架自动注入。
            """
            try:
                # 认证检查
                if not self._validate_auth(ctx):
                    return ChimeraResult(
                        success=False,
                        data={"research_context": None},
                        message="Authentication failed"
                    )
                
                logger.debug(f"Deep research request: page_id={params.page_id}, complexity={params.research_complexity}")
                
                # 创建内部请求（添加固定参数）
                internal_request = DeepResearchRequest(
                    page_id=params.page_id,
                    purpose=params.purpose,  # 必需字段，直接传递
                    max_pages=params.max_pages,
                    research_complexity=params.research_complexity,
                    depth=4,  # 固定
                    max_workers=4  # 固定
                )
                
                # 执行深度研究
                director = ContextEngineeringDirector()
                research_context = await director.orchestrate_research(internal_request)
                
                logger.debug(f"Deep research completed successfully")
                
                return ChimeraResult(
                    success=True,
                    data={
                        "research_context": research_context.model_dump(),
                        "complexity_applied": params.research_complexity,
                        "pages_analyzed": params.max_pages,
                        "processing_metadata": {
                            "workers_used": 4,
                            "depth_traversed": 4,
                            "api_calls_made": director.api_call_count,
                            "processing_time_seconds": director.processing_time,
                            "clusters_formed": len(research_context.topic_clusters),
                            "top_pages_selected": len(research_context.top_pages)
                        }
                    },
                    message=f"研究完成：{params.research_complexity}级分析，{len(research_context.top_pages)}个顶级页面，{len(research_context.topic_clusters)}个主题簇"
                )
                
            except ValueError as ve:
                # 页面验证失败等业务逻辑错误
                logger.warning(f"Deep research validation failed: {ve}")
                return ChimeraResult(
                    success=False,
                    data={"research_context": None},
                    message=f"研究验证失败: {str(ve)}"
                )
                
            except Exception as e:
                logger.exception(f"Error in deep_research: {e}")
                return ChimeraResult(
                    success=False,
                    data={"research_context": None},
                    message=f"深度研究失败: {str(e)}"
                )

        # ==================== GPT MCP标准工具 ====================

        @self.mcp.tool(
            title="搜索页面ID（Notion）",
            description=(
                "GPT MCP标准search工具 - 搜索Notion并返回相关页面ID列表。\n\n"
                "**功能**：从Notion知识库中搜索相关页面，返回页面ID、标题、URL列表。\n\n"
                "**参数**：\n"
                "- query (str): 搜索查询字符串\n\n"
                "**返回格式**：\n"
                "```json\n"
                "{\n"
                "  \"results\": [\n"
                "    {\"id\": \"page-id-1\", \"title\": \"页面标题1\", \"url\": \"https://...\"},\n"
                "    {\"id\": \"page-id-2\", \"title\": \"页面标题2\", \"url\": \"https://...\"}\n"
                "  ]\n"
                "}\n"
                "```\n\n"
                "**使用建议**：先使用此工具获取ID列表，再使用fetch工具按需获取内容。"
            )
        )
        async def search(query: str, ctx: Context):
            """GPT MCP标准search工具 - ChatGPT兼容版本"""
            try:
                # 认证检查
                if not self._validate_auth(ctx):
                    return {
                        "content": [{
                            "type": "text",
                            "text": json.dumps({"results": []}, ensure_ascii=False)
                        }]
                    }

                logger.debug(f"Search tool request: query={query}")

                # 创建搜索引擎实例
                engine = IntentSearchEngine()

                # 调用search_only获取ID列表（使用默认参数：speed=True, max_results=5）
                results = await engine.search_only(
                    query=query,
                    speed=True,  # 默认使用速度模式
                    max_results=5  # 默认返回5个结果
                )

                # 构建GPT MCP标准响应
                response = SearchToolResponse(
                    results=[SearchResultItem(**r) for r in results]
                )

                logger.debug(f"Search tool completed: {len(results)} results found")

                # 返回GPT MCP标准格式
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(response.model_dump(), ensure_ascii=False)
                    }]
                }

            except Exception as e:
                logger.exception(f"Error in search tool: {e}")
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({"results": []}, ensure_ascii=False)
                    }]
                }

        @self.mcp.tool(
            title="获取页面内容（Notion）",
            description=(
                "GPT MCP标准fetch工具 - 根据页面ID批量获取完整路径内容。\n\n"
                "**功能**：并发获取多个Notion页面及其完整路径上所有页面的内容。\n\n"
                "**参数**：\n"
                "- id (str): 页面ID字符串，支持三种格式：\n"
                "  1. 单个ID: 'page-id-1'\n"
                "  2. 逗号分隔: 'page-id-1,page-id-2,page-id-3'\n"
                "  3. JSON数组: '[\"page-id-1\", \"page-id-2\"]'\n\n"
                "**返回格式**：\n"
                "```json\n"
                "{\n"
                "  \"results\": [\n"
                "    {\n"
                "      \"id\": \"leaf-page-id\",\n"
                "      \"title\": \"叶子页面标题\",\n"
                "      \"text\": \"叶子页面完整内容...\",\n"
                "      \"url\": \"https://...\",\n"
                "      \"metadata\": {\n"
                "        \"last_edited_time\": \"2024-01-01T00:00:00\",\n"
                "        \"content_length\": 5000,\n"
                "        \"path_string\": \"Root -> Parent -> Leaf\",\n"
                "        \"path_contents\": [\n"
                "          {\"title\": \"Root\", \"content\": \"...\", \"position\": 0},\n"
                "          {\"title\": \"Parent\", \"content\": \"...\", \"position\": 1},\n"
                "          {\"title\": \"Leaf\", \"content\": \"...\", \"position\": 2, \"is_leaf\": true}\n"
                "        ],\n"
                "        \"total_path_pages\": 3\n"
                "      }\n"
                "    }\n"
                "  ]\n"
                "}\n"
                "```\n\n"
                "**特性**：\n"
                "- 自动获取完整路径上所有页面的内容\n"
                "- text字段为叶子页面主内容\n"
                "- metadata.path_contents包含路径上所有页面内容\n\n"
                "**使用建议**：配合search工具使用，先搜索获取ID列表，再选择性获取完整路径内容。"
            )
        )
        async def fetch(id: str, ctx: Context):
            """GPT MCP标准fetch工具 - ChatGPT兼容版本"""
            try:
                # 认证检查
                if not self._validate_auth(ctx):
                    return {
                        "content": [{
                            "type": "text",
                            "text": json.dumps({"results": []}, ensure_ascii=False)
                        }]
                    }

                # 解析id字符串为ID列表
                page_ids = self._parse_page_ids(id)

                if not page_ids:
                    logger.warning(f"Invalid id format: {id}")
                    return {
                        "content": [{
                            "type": "text",
                            "text": json.dumps({"results": []}, ensure_ascii=False)
                        }]
                    }

                logger.debug(f"Fetch tool request: page_ids={page_ids} (parsed from: {id})")

                # 创建搜索引擎实例
                engine = IntentSearchEngine()

                # 调用fetch_by_ids获取内容
                results = await engine.fetch_by_ids(
                    page_ids=page_ids,
                    include_children=False  # 默认不包含子页面
                )

                # 构建GPT MCP标准响应
                response = FetchToolResponse(
                    results=[FetchResultItem(**r) for r in results]
                )

                logger.debug(f"Fetch tool completed: {len(results)} pages fetched")

                # 返回GPT MCP标准格式
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(response.model_dump(), ensure_ascii=False)
                    }]
                }

            except Exception as e:
                logger.exception(f"Error in fetch tool: {e}")
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({"results": []}, ensure_ascii=False)
                    }]
                }

        # ==================== 个人记忆写入工具 ====================

        @self.mcp.tool(
            title="写入个人记忆（我的关系图谱）",
            description=(
                "记录我（陈宇函/肥猫）与他人或事物的关系信息到知识图谱。\n\n"
                "**工作原理**:\n"
                "- 输入自然语言描述，可以用'我'代表陈宇函\n"
                "- Graphiti自动理解上下文并提取实体和关系\n"
                "- 存储到个人记忆图谱，可通过'社交关系搜索'检索\n\n"
                "**适用场景**:\n"
                "- 人际关系: '我和JZX是同事关系'\n"
                "- 项目参与: '我于2025年9月30日参与了GREEN项目的开发'\n"
                "- 个人偏好: '我喜欢用Python写代码'\n"
                "- 事件记录: '我上周参加了技术分享会'\n"
                "- 推荐记录: 'JZX推荐我看《代码大全》'\n\n"
                "**参数**:\n"
                "- content (str): 记忆内容（自然语言）\n"
                "- memory_type (str): relationship|preference|event|fact\n\n"
                "**特点**:\n"
                "- 自动识别实体和关系\n"
                "- 支持复杂关系描述\n"
                "- 与微信关系图谱统一检索"
                "**注意**："
                "-必须把今天 昨天等日期转化为准确的时间 （年月日 时分秒）"
                "-Content要有总结性，简洁方便知识图谱构造就行, 最多字数为150字"
            )
        )
        async def write_personal_memory_tool(params: PersonalMemoryInput, ctx: Context) -> ChimeraResult:
            """个人记忆写入工具"""
            try:
                # 认证检查
                if not self._validate_auth(ctx):
                    return ChimeraResult(
                        success=False,
                        data={},
                        message="Authentication failed"
                    )

                logger.debug(f"Writing personal memory: type={params.memory_type}, content_length={len(params.content)}")

                # 调用写入函数
                result = await write_personal_memory(
                    content=params.content,
                    memory_type=params.memory_type,
                    source="chatgpt"
                )

                if result["success"]:
                    return ChimeraResult(
                        success=True,
                        data={
                            "memory_id": result.get("memory_id"),
                            "memory_type": params.memory_type,
                            "group_id": "personal_memories"
                        },
                        message=result["message"]
                    )
                else:
                    return ChimeraResult(
                        success=False,
                        data={},
                        message=result["message"]
                    )

            except Exception as e:
                logger.exception(f"Error in write_personal_memory_tool: {e}")
                return ChimeraResult(
                    success=False,
                    data={},
                    message=f"写入记忆失败: {str(e)}"
                )

    def run(self, host: str = "0.0.0.0", port: int = 3000):
        """启动Streamable HTTP MCP服务器"""
        # logger.info(f"Starting Chimera FastMCP Server on http://{host}:{port}/mcp")

        try:
            # 使用Streamable HTTP传输运行服务器，兼容mcp-remote
            self.mcp.run(
                transport="http",
                host=host,
                port=port,
                stateless_http=True  # 启用无状态HTTP模式
            )
        except Exception as e:
            logger.exception(f"Error running FastMCP server: {e}")
            raise


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description="Chimera FastMCP HTTP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=3000, help="Port to bind to")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    
    args = parser.parse_args()
    
    # 简单的日志设置
    logger.remove()  # 移除默认处理器
    logger.add(sys.stderr, level=args.log_level)
    
    # 获取设置，自动从.env文件加载
    try:
        settings = get_settings()
        logger.info(f"Starting server on {args.host}:{args.port}")
        logger.info(f"认证: {'启用' if settings.enable_auth else '禁用'}")
        
        if settings.enable_auth and settings.chimera_api_key:
            logger.info(f"API Key 前缀: {settings.chimera_api_key[:8]}...")
    except Exception as e:
        logger.error(f"配置加载失败: {e}")
        sys.exit(1)
    
    server = ChimeraFastMCPServer()
    server.run(host=args.host, port=args.port)

def kill_port(port):
    try:
        # 使用 lsof 查找占用端口的 PID（仅适用于 macOS/Linux）
        result = subprocess.run(
            ["lsof", "-i", f":{port}"], capture_output=True, text=True
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) > 1:
            for line in lines[1:]:
                pid = int(line.split()[1])
                logger.info(f"Killing process on port {port}, PID: {pid}")
                os.kill(pid, 9)
    except Exception as e:
        logger.warning(f"Failed to kill process on port {port}: {e}")

if __name__ == "__main__":
    kill_port(3000)  # 在启动主程序前尝试释放端口
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.exception(f"Server error: {e}")
        sys.exit(1)