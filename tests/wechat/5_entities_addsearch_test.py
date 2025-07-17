#!/usr/bin/env python3
"""
测试5个Entity Episodes的搜索效果
"""

import asyncio
import sys
from pathlib import Path

# 确保项目根目录在Python路径中
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from tests.wechat.entity_extraction import extract_entity_episodes
from core.wechat_graphiti_client import WeChatGraphitiClient
from datetime import datetime, timezone

async def a_5_entities():
    """测试5个Entity Episodes"""
    logger.info("测试5个Entity Episodes的搜索效果")
    
    # 从GREEN研发文件提取几个Entity
    json_file = "local_data/wechat/group/GREEN研发_2025-07-15.json"
    episodes = extract_entity_episodes(json_file)
    
    # 只取前5个
    test_episodes = episodes[:5]
    
    logger.info(f"选择了 {len(test_episodes)} 个Episodes进行测试:")
    for i, episode in enumerate(test_episodes):
        logger.info(f"{i+1}. {episode['name']} ({episode['entity_type']})")
    
    # 转换为Graphiti格式
    graphiti_episodes = []
    for episode in test_episodes:
        graphiti_episode = {
            "name": episode["name"],
            "episode_body": episode["episode_body"],
            "source_description": episode["source_description"],
            "reference_time": datetime.now(timezone.utc)
        }
        graphiti_episodes.append(graphiti_episode)
    
    # 存储到数据库
    client = WeChatGraphitiClient()
    try:
        await client.initialize()
        
        # 存储Episodes
        logger.info(f"存储 {len(graphiti_episodes)} 个Episodes...")
        result = await client.add_graphiti_episodes_bulk(graphiti_episodes)

        if result.success:
            logger.info(f"✅ 成功存储 {result.total_episodes} 个Episodes")
        else:
            logger.error(f"❌ 存储失败: {result.errors}")
            return False

        # 等待数据库处理
        await asyncio.sleep(2)
        
        # 测试搜索
        logger.info("\n开始搜索测试...")
        
        test_queries = [
            'yvnn',
            'GREEN研发',
            'AI碳经济项目',
            'ゞ肥の猫ゞ',
            '奶豆跟你拼了'
        ]
        
        for query in test_queries:
            logger.info(f"\n=== 搜索: {query} ===")
            
            results = await client.search_episodes(query, limit=3)
            
            if results:
                logger.info(f"找到 {len(results)} 个结果:")
                for i, result in enumerate(results):
                    fact = result.get('fact', '')
                    score = result.get('score', 0.0)
                    
                    # 判断相关性
                    is_relevant = query.lower() in fact.lower()
                    status = "✅" if is_relevant else "❌"
                    
                    logger.info(f"  {i+1}. {status} (得分: {score:.4f})")
                    logger.info(f"     {fact[:100]}...")
            else:
                logger.info("没有找到结果")
        
        logger.info("\n✅ 测试完成")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        return False
    finally:
        await client.close()

if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    
    asyncio.run(a_5_entities())