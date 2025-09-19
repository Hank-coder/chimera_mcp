#!/usr/bin/env python3
"""
Notion Webhook服务器
提供 /notion/webhook 端点接收Notion实时推送的页面变更事件
"""

import asyncio
import json
import subprocess
import time
import threading
import re
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
from asyncio import Queue

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import uvicorn

from config.settings import get_settings, settings
from config.logging import setup_logging
from sync_service.webhook_handler import NotionWebhookHandler

# 全局变量
app = FastAPI(
    title="Chimera Webhook Server",
    description="Notion Webhook处理服务器",
    version="1.0.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局变量
webhook_handler: NotionWebhookHandler = None
tunnel_process: Optional[subprocess.Popen] = None
event_queue: Queue = None
queue_worker_task: Optional[asyncio.Task] = None


def start_tunnel(port: int) -> Tuple[Optional[subprocess.Popen], Optional[str]]:
    """启动ngrok隧道"""

    logger.info("🚇 启动 ngrok 隧道...")
    try:
        # 检查ngrok是否安装且已认证
        result = subprocess.run(["ngrok", "version"], capture_output=True, check=True)

        # 启动ngrok
        ngrok_process = subprocess.Popen([
            "ngrok", "http", str(port)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # 等待ngrok启动
        time.sleep(3)

        # 获取ngrok URL
        try:
            result = subprocess.run([
                "curl", "-s", "http://localhost:4040/api/tunnels"
            ], capture_output=True, text=True)

            tunnels = json.loads(result.stdout)

            for tunnel in tunnels.get("tunnels", []):
                if tunnel.get("proto") == "https":
                    ngrok_url = tunnel["public_url"]
                    return ngrok_process, ngrok_url

        except Exception as e:
            logger.warning(f"⚠️  获取ngrok URL失败: {e}")
            logger.info("可以访问 http://localhost:4040 查看ngrok状态")

        return ngrok_process, None

    except subprocess.CalledProcessError as e:
        if "authentication failed" in str(e) or "authtoken" in str(e):
            logger.error("❌ ngrok需要认证，请访问 https://dashboard.ngrok.com/get-started/your-authtoken")
        else:
            logger.error("❌ ngrok 未安装或不可用")
        return None, None
    except Exception as e:
        logger.error(f"❌ ngrok 启动失败: {e}")
        return None, None


async def queue_worker():
    """队列工作器，依次处理webhook事件"""
    global event_queue, webhook_handler

    logger.info("🔄 Webhook事件队列工作器启动")

    while True:
        try:
            # 从队列获取事件
            event_data = await event_queue.get()

            if event_data is None:  # 退出信号
                logger.info("🛑 收到退出信号，停止队列工作器")
                break

            start_time = datetime.now()
            event_type = event_data.get("type", "unknown")
            entity_id = event_data.get("entity", {}).get("id", "unknown")

            logger.info(f"🔄 [队列] 开始处理事件: {event_type} for entity {entity_id}")

            # 调用webhook处理器
            if webhook_handler:
                result = await webhook_handler.handle_webhook_event(event_data)

                processing_time = (datetime.now() - start_time).total_seconds()

                if result.get("success", False):
                    logger.info(f"✅ [队列] 事件处理成功 {processing_time:.2f}s: {result}")
                else:
                    logger.error(f"❌ [队列] 事件处理失败 {processing_time:.2f}s: {result}")
            else:
                logger.error("❌ [队列] Webhook handler未初始化")

            # 标记任务完成
            event_queue.task_done()

        except Exception as e:
            logger.exception(f"❌ [队列] 处理事件时出错: {e}")

            # 记录详细错误信息到错误日志
            error_details = {
                "event_type": event_data.get("type", "unknown"),
                "entity_id": event_data.get("entity", {}).get("id", "unknown"),
                "error_message": str(e),
                "timestamp": datetime.now().isoformat(),
                "event_data": event_data
            }
            logger.error(f"❌ [错误详情] {json.dumps(error_details, indent=2, ensure_ascii=False)}")

            # 确保标记任务完成，避免队列卡住
            try:
                event_queue.task_done()
            except Exception as task_done_error:
                logger.error(f"❌ 标记队列任务完成时出错: {task_done_error}")


@app.on_event("startup")
async def startup_event():
    """服务器启动时初始化"""
    global webhook_handler, tunnel_process, event_queue, queue_worker_task

    # 获取配置
    settings = get_settings()

    logger.info("🚀 Starting Chimera Webhook Server...")
    logger.info(f"📱 Device type: {settings.device}")

    # 如果是本地环境，启动隧道
    if settings.device.upper() == "LOCAL":
        logger.info("🏠 检测到本地环境，启动隧道...")
        port = 8081  # webhook服务器端口
        tunnel_process, tunnel_url = start_tunnel(port)

        if tunnel_process and tunnel_url:
            logger.info(f"🔗 [local] 请将以下 URL 配置到 Notion webhook：")
            logger.info(f"{tunnel_url}/notion/webhook")
        else:
            logger.error("❌ 隧道启动失败，但服务器将继续运行")
    else:
        logger.info("🖥️  服务器模式，直接监听端口")

    # 初始化事件队列
    event_queue = Queue()
    logger.info("📋 事件队列已初始化")

    # 初始化webhook处理器
    try:
        webhook_handler = NotionWebhookHandler()
        await webhook_handler.initialize()
        logger.info("✅ Webhook handler initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize webhook handler: {e}")
        raise

    # 启动队列工作器
    queue_worker_task = asyncio.create_task(queue_worker())
    logger.info("🔄 队列工作器已启动")


@app.on_event("shutdown")
async def shutdown_event():
    """服务器关闭时清理"""
    global tunnel_process, event_queue, queue_worker_task
    logger.info("🛑 Shutting down Chimera Webhook Server...")

    # 停止队列工作器
    if event_queue and queue_worker_task:
        logger.info("📋 停止事件队列工作器...")
        try:
            # 发送停止信号
            await event_queue.put(None)
            # 等待工作器完成
            await asyncio.wait_for(queue_worker_task, timeout=10.0)
            logger.info("✅ 队列工作器已停止")
        except asyncio.TimeoutError:
            logger.warning("⚠️  队列工作器停止超时，强制取消")
            queue_worker_task.cancel()
        except Exception as e:
            logger.warning(f"⚠️  停止队列工作器时出错: {e}")

    # 清理隧道进程
    if tunnel_process:
        logger.info("🚇 停止隧道进程...")
        try:
            tunnel_process.terminate()
            tunnel_process.wait(timeout=5)
            logger.info("✅ 隧道进程已停止")
        except Exception as e:
            logger.warning(f"⚠️  停止隧道进程时出错: {e}")
            try:
                tunnel_process.kill()
            except:
                pass


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Chimera Webhook Server",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "webhook": "/notion/webhook",
            "health": "/health"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "webhook_handler": "initialized" if webhook_handler else "not_initialized"
    }


@app.post("/notion/webhook")
async def notion_webhook(request: Request):
    """
    Notion Webhook端点
    处理Notion发送的页面变更事件
    """
    try:
        # 获取请求体
        body = await request.body()

        # 获取签名头
        signature = request.headers.get("X-Notion-Signature", "")

        # 验证签名
        if not webhook_handler.verify_webhook_signature(body, signature):
            logger.warning("Webhook signature verification failed")
            raise HTTPException(status_code=401, detail="Invalid signature")

        # 解析JSON数据
        try:
            event_data = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON")

        # 基本日志记录
        logger.info(
            f"📨 Notion {event_data.get('type', 'unknown')} - {event_data.get('entity', {}).get('id', 'unknown')}")

        # 显示详细调试信息（帮助排查问题）
        logger.info(f"🔍 [DEBUG] 完整webhook数据: {json.dumps(event_data, indent=2, ensure_ascii=False)}")
        logger.info(f"🔍 [DEBUG] 请求头: {dict(request.headers)}")
        logger.info(f"🔍 [DEBUG] 请求体大小: {len(body)} bytes")

        # 检查是否是挑战验证
        if event_data.get("type") == "challenge":
            challenge_response = await handle_challenge(event_data)
            return challenge_response

        # 记录接收到的事件
        event_type = event_data.get("type", "unknown")
        entity_id = event_data.get("entity", {}).get("id", "unknown")
        logger.debug(f"📄 处理webhook事件: {event_type} for entity {entity_id}")

        # 将事件加入队列进行顺序处理
        await event_queue.put(event_data)
        logger.debug(f"📋 事件已加入队列: {event_type} for entity {entity_id}")

        # 立即返回成功响应给Notion
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Webhook received and queued for processing",
                "event_type": event_type,
                "entity_id": entity_id,
                "timestamp": datetime.now().isoformat()
            }
        )

    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        logger.exception(f"Unexpected error in webhook endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def handle_challenge(event_data: Dict[str, Any]):
    """
    处理Notion webhook的挑战验证
    在设置webhook时，Notion会发送挑战请求来验证端点
    """
    challenge_value = event_data.get("challenge")

    if not challenge_value:
        logger.error("❌ Challenge request missing challenge value")
        raise HTTPException(status_code=400, detail="Missing challenge value")

    # 详细的challenge日志 - 仅用于首次配置
    logger.info(f"\n🎯 SUCCESS! 收到Challenge Token: {challenge_value}")
    logger.info(f"✅ Webhook验证完成！首次配置成功")
    logger.info(f"🔐 返回challenge给Notion完成验证")

    # Notion要求返回纯文本格式的challenge值
    return PlainTextResponse(
        content=challenge_value,
        status_code=200,
        headers={"Content-Type": "text/plain"}
    )


# 错误处理
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": f"Path {request.url.path} not found",
            "available_endpoints": ["/", "/health", "/notion/webhook"]
        }
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.exception(f"Internal server error on {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred",
            "timestamp": datetime.now().isoformat()
        }
    )


def main():
    """主函数"""
    import sys
    import argparse
    import os
    from pathlib import Path

    # 参数解析
    parser = argparse.ArgumentParser(description="Chimera Webhook Server")
    parser.add_argument("--host", default="0.0.0.0", help="服务器主机地址")
    parser.add_argument("--port", type=int, default=8081, help="服务器端口")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument("--ssl", action="store_true", help="启用HTTPS/SSL")
    parser.add_argument("--ssl-cert", default="config/cyhank.com.crt", help="SSL证书文件路径")
    parser.add_argument("--ssl-key", default="config/cyhank.com.key", help="SSL私钥文件路径")

    args = parser.parse_args()

    # 设置日志
    setup_logging()

    # 获取配置
    settings = get_settings()

    logger.info("=" * 60)
    logger.info("🔗 Chimera Webhook Server")
    logger.info("=" * 60)
    logger.info(f"Host: {args.host}:{args.port}")
    logger.info(f"SSL/HTTPS: {args.ssl}")
    logger.info(f"Debug: {args.debug}")
    logger.info(f"Environment: {settings.app_environment}")

    # SSL配置
    ssl_config = {}
    if settings.device.upper() == "SERVER":
        ssl_cert_path = Path(args.ssl_cert)
        ssl_key_path = Path(args.ssl_key)

        # 检查证书文件是否存在，存在就使用SSL，不存在就跳过
        if ssl_cert_path.exists() and ssl_key_path.exists():
            ssl_config = {
                "ssl_keyfile": str(ssl_key_path),
                "ssl_certfile": str(ssl_cert_path)
            }
            logger.info(f"✅ SERVER模式启用SSL: {ssl_cert_path}")
        else:
            logger.warning("⚠️ SSL证书文件不存在，使用HTTP模式")
            logger.info("💡 建议配置反向代理(如Nginx)提供HTTPS支持")
            logger.info(f"  期望的证书路径: {ssl_cert_path}")
            logger.info(f"  期望的密钥路径: {ssl_key_path}")
    else:
        logger.info("🏠 LOCAL 模式，不启用 SSL")

    try:
        # 启动服务器
        uvicorn_args = {
            "app": "webhook_server:app",
            "host": args.host,
            "port": args.port,
            "reload": args.debug,
            "log_level": "info" if not args.debug else "debug",
            **ssl_config,  # 自动添加 ssl 参数（如果是 SERVER 模式）
        }
        uvicorn.run(**uvicorn_args)

    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"❌ Server failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()