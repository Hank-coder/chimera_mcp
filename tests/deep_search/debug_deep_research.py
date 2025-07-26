#!/usr/bin/env python3
"""
Deep Research调试脚本
用于复现和调试语义分簇JSON解析错误
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.deep_research.director import ContextEngineeringDirector
from core.models import DeepResearchRequest
from loguru import logger

async def debug_deep_research():
    """调试Deep Research功能"""
    
    try:
        # 创建Director实例
        director = ContextEngineeringDirector()
        
        # 创建一个简单的测试请求
        # 使用真实的页面ID
        request = DeepResearchRequest(
            page_id="22dccc690d8280e48e28cc45b8596548",  # 从Notion链接提取的页面ID
            purpose="调试测试语义分簇JSON解析",
            max_pages=5,
            research_complexity="standard"
        )
        
        logger.info("开始调试Deep Research...")
        
        # 尝试执行研究流程
        try:
            result = await director.orchestrate_research(request)
            logger.info("Deep Research调试完成")
            print(f"结果类型: {type(result)}")
            
        except Exception as e:
            logger.error(f"Deep Research执行失败: {e}")
            logger.exception("详细错误堆栈:")
            
    except Exception as e:
        logger.error(f"初始化失败: {e}")
        logger.exception("详细错误堆栈:")

if __name__ == "__main__":
    print("🔍 开始Deep Research调试...")
    asyncio.run(debug_deep_research())
    print("✅ 调试完成")