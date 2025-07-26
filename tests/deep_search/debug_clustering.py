#!/usr/bin/env python3
"""
专门调试语义分簇的脚本
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.deep_research.director import ContextEngineeringDirector
from loguru import logger

async def debug_clustering():
    """调试语义分簇功能"""
    
    try:
        # 创建Director实例
        director = ContextEngineeringDirector()
        
        # 创建模拟的页面数据
        mock_pages = [
            {
                "notion_id": "page1",
                "title": "深度学习基础",
                "tags": ["AI", "机器学习"],
                "level": 1,
                "distance_from_root": 1
            },
            {
                "notion_id": "page2", 
                "title": "神经网络架构",
                "tags": ["AI", "神经网络"],
                "level": 1,
                "distance_from_root": 1
            },
            {
                "notion_id": "page3",
                "title": "Python编程技巧",
                "tags": ["编程", "Python"],
                "level": 1,
                "distance_from_root": 1
            },
            {
                "notion_id": "page4",
                "title": "数据处理方法",
                "tags": ["数据科学", "分析"],
                "level": 1,
                "distance_from_root": 1
            }
        ]
        
        logger.info("开始测试语义分簇...")
        
        # 直接调用语义分簇方法
        try:
            clusters = await director.semantic_clustering(mock_pages, 3, "standard")
            logger.info(f"分簇成功：{len(clusters)} 个簇")
            for i, cluster in enumerate(clusters):
                logger.info(f"簇 {i+1}: {len(cluster)} 个页面")
                
        except Exception as e:
            logger.error(f"语义分簇失败: {e}")
            logger.exception("详细错误:")
            
    except Exception as e:
        logger.error(f"初始化失败: {e}")
        logger.exception("详细错误:")

if __name__ == "__main__":
    print("🔍 开始语义分簇调试...")
    asyncio.run(debug_clustering())
    print("✅ 调试完成")