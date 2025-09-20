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
from typing import Dict, Any
from fastmcp import FastMCP, Context
from pydantic import BaseModel, Field
from loguru import logger

# 确保项目根目录在Python路径中
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.intent_search import search_user_intent
from agents.deep_research import ContextEngineeringDirector
from utils.fastmcp_utils import get_bearer_token, get_path_contents_async
from config.settings import get_settings
from core.wechat_search import search_wechat_relationships
from core.models import DeepResearchRequest


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
    
    def _setup_tools(self):
        """设置MCP工具"""

        @self.mcp.tool(
            title="文档标准搜索（Notion）",
            description=(
                    "这是我（陈宇函）的个人知识库Chimera**简单/标准搜索**工具，侧重于单文档。"
                    "用于从第二大脑（Notion）中查找相关笔记、记录、项目、总结等内容。\n\n"
                    "🔍 **搜索模式**：\n"
                    " - 标准模式 (speed=false)：使用LLM判断+embedding搜索的混合策略，准确性高\n"
                    " - 速度模式 (speed=true)：仅使用embedding语义搜索，速度快\n\n"
                    "调用时请传入以下参数（字段名区分大小写，必须严格对应）：\n"
                    " - query (字符串，必填)：搜索关键词或短语（如有时间信息请包含），示例：\"上周碳中和计划\"\n"
                    " - search_results (整数，默认5)：返回的最大搜索结果条数\n"
                    " - speed (布尔值，默认true)：速度模式开关，true=仅embedding搜索（快），false=混合搜索（准确）\n"
                    "⚡ **性能建议**：高准确性时使用标准模式；快速查找使用速度模式。\n\n"
                    "示例参数JSON格式：\n"
                    "{\n"
                    "  \"query\": \"碳中和项目进展\",\n"
                    "  \"search_results\": 5,\n"
                    "  \"speed\": true\n"
                    "}"
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
                        
                        # 如果有完整路径信息，获取所有页面内容
                        if core_page.path_ids and core_page.path_titles:
                            path_contents = await get_path_contents_async(
                                self.notion_client,
                                core_page.path_titles, 
                                core_page.path_ids,
                                include_files=True,  # 默认提取文档
                                max_content_length=params.max_page_content_length,
                                max_file_content_length=params.max_file_content_length
                            )
                            
                            # 获取叶子页面（最后一个页面）的时间信息
                            leaf_time = ""
                            if path_contents:
                                leaf_page = path_contents[-1]  # 叶子页面是路径中的最后一个
                                leaf_time = leaf_page.get("last_edited_time", "")
                            
                            path_data = {
                                "path": core_page.path_string,
                                "confidence": core_page.confidence_score,
                                "last_edited_time": leaf_time,
                                "path_contents": path_contents,
                                "total_pages": len(path_contents)
                            }
                        else:
                            # 备用：单页面结果，从JSON缓存获取时间
                            import json
                            from pathlib import Path
                            page_time = ""
                            try:
                                cache_file = Path("llm_cache/chimera_cache.json")
                                if cache_file.exists():
                                    with open(cache_file, 'r', encoding='utf-8') as f:
                                        cache_data = json.load(f)
                                        pages = cache_data.get("pages", {})
                                        page_info = pages.get(core_page.notion_id, {})
                                        page_time = page_info.get("lastEditedTime", "")
                            except Exception:
                                pass
                            
                            path_data = {
                                "path": core_page.title,
                                "confidence": core_page.confidence_score,
                                "last_edited_time": page_time,
                                "notion_id": core_page.notion_id,
                                "title": core_page.title,
                                "content": core_page.content
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
            title="社交关系搜索（微信）",
            description=(
                "这是我 *ゞ肥の猫ゞ* **（陈宇函）的微信社交关系图谱搜索工具，"
                "用于从微信聊天记录中查找人际关系、群组成员、活动参与等社交信息。\n\n"
                "特别适用于以下场景：\n"
                " - 人名查询：例如 \"敏哥\"、\"JZX\"\n"
                " - 项目查询：例如 \"GREEN项目\"、\"研发项目\"\n"
                " - 关系查询：例如 \"谁参与了GREEN项目\"、\"肥猫是什么角色\"\n\n"
                "调用时请传入以下参数（字段名区分大小写，必须严格对应）：\n"
                " - query (字符串，必填)：关系查询问题，可以是人名、项目名或关系问题\n"
                " - max_results (整数，默认3 最大为10)：返回的最大搜索结果数量\n\n"
                "搜索返回格式：\n"
                " - Top1节点：主要匹配实体 + 所有相关实体的摘要\n"
                " - Top2-3节点：次要匹配实体的摘要\n\n"
                "示例查询：\n"
                "{\n"
                "  \"query\": \"敏哥\",\n"
                "  \"max_results\": 3\n"
                "}"
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
    
    def run(self, host: str = "0.0.0.0", port: int = 3000):
        """启动Streamable HTTP MCP服务器"""
        logger.info(f"Starting Chimera FastMCP Server on http://{host}:{port}/mcp")
        
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