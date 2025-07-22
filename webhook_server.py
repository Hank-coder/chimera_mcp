#!/usr/bin/env python3
"""
Notion Webhook服务器
提供 /notion/webhook 端点接收Notion实时推送的页面变更事件
"""

import asyncio
import json
import subprocess
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import uvicorn

from config.settings import get_settings
from config.logging import setup_logging
from sync_service.webhook_handler import NotionWebhookHandler

app = FastAPI(
    title="Chimera Webhook Server",
    description="Notion Webhook处理服务器",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

webhook_handler: NotionWebhookHandler = None

@app.on_event("startup")
async def startup_event():
    global webhook_handler
    settings = get_settings()
    logger.info("🚀 启动 Chimera Webhook Server")
    try:
        webhook_handler = NotionWebhookHandler()
        await webhook_handler.initialize()
        logger.info("✅ Webhook handler 初始化成功")
    except Exception as e:
        logger.error(f"❌ Webhook handler 初始化失败: {e}")
        raise

@app.get("/")
async def root():
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
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "webhook_handler": "initialized" if webhook_handler else "not_initialized"
    }

@app.post("/notion/webhook")
async def notion_webhook(request: Request):
    try:
        body = await request.body()
        signature = request.headers.get("X-Notion-Signature", "")

        if not webhook_handler.verify_webhook_signature(body, signature):
            logger.warning("Webhook signature verification failed")
            raise HTTPException(status_code=401, detail="Invalid signature")

        try:
            event_data = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON")

        if event_data.get("type") == "challenge":
            return PlainTextResponse(content=event_data["challenge"], status_code=200)

        logger.info(f"📨 Notion {event_data.get('type')} - {event_data.get('entity', {}).get('id')}")
        return JSONResponse(status_code=200, content={"success": True})

    except Exception as e:
        logger.exception(f"❌ Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": "Not Found", "message": f"{request.url.path} not found"}
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.exception(f"500 error on {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "timestamp": datetime.now().isoformat()}
    )

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    setup_logging()
    logger.info("🔗 Chimera Webhook Server starting")

    uvicorn.run(
        "webhook_server:app",
        host=args.host,
        port=args.port,
        reload=args.debug,
        log_level="debug" if args.debug else "info"
    )

if __name__ == "__main__":
    main()
