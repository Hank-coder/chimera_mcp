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
from utils.fastmcp_utils import get_bearer_token, get_path_contents_async
from config.settings import get_settings


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

    confidence_threshold: float = Field(
        0.8,
        description=(
            "最低置信度分数（0.5-1.0），用于过滤低置信度结果。"
            "默认值为 0.8，表示仅返回高度相关的路径。"
            "如需扩大召回范围，可设置为更低值（如 0.65）。"
        )
    )

    search_results: int = Field(
        3,
        description=(
            "返回的搜索结果数量，默认返回 3 条相关路径。"
            "可根据需要调整数量上限。"
        )
    )

    expansion_depth: int = Field(
        1,
        description=(
            "路径扩展深度。用于向外关联更多上下游页面，默认值为 1，表示仅获取直接相关页面。"
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
            title="🧠 个人记忆搜索（Notion）",
            description=(
                    "这是我（陈宇函）的个人知识库“Chimera”搜索工具，"
                    "用于从第二大脑（Notion）中查找相关笔记、记录、项目、总结等内容。\n\n"
                    "调用时请传入以下参数（字段名区分大小写，必须严格对应）：\n"
                    " - query (字符串，必填)：搜索关键词或短语，示例：\"碳中和 计划\"\n"
                    " - confidence_threshold (浮点数，默认0.8)：最低置信度阈值，范围0.5-1.0，用于过滤搜索结果。\n"
                    " - search_results (整数，默认3)：返回的最大搜索结果条数。\n"
                    " - expansion_depth (整数，默认1)：路径扩展深度，决定关联更多上下游页面的层级。\n"
                    " - max_file_content_length (整数，默认8000)：单个文档文件内容最大字符数限制。\n"
                    " - max_page_content_length (整数，默认10000)：单个Notion页面内容最大字符数限制。\n\n"
                    "请确保参数名称和类型正确，避免使用其他相似但不一致的名称。\n"
                    "示例参数JSON格式：\n"
                    "{\n"
                    "  \"query\": \"碳中和\",\n"
                    "  \"confidence_threshold\": 0.8,\n"
                    "  \"search_results\": 3,\n"
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
                
                logger.info(f"Intent search request: {params.query}")
                
                result = await search_user_intent(
                    user_input=params.query,
                    confidence_threshold=params.confidence_threshold,
                    search_results=params.search_results,
                    expansion_depth=params.expansion_depth
                )
                
                logger.info(f"Intent search completed, success: {result.success}")
                
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
                            
                            path_data = {
                                "path": core_page.path_string,
                                "confidence": core_page.confidence_score,
                                "path_contents": path_contents,
                                "total_pages": len(path_contents)
                            }
                        else:
                            # 备用：单页面结果
                            path_data = {
                                "path": core_page.title,
                                "confidence": core_page.confidence_score,
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