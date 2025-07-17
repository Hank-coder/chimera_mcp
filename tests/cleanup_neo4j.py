#!/usr/bin/env python3
"""
清理被污染的neo4j数据库，恢复NotionPage and SyncMetadata Node
"""

import sys
import asyncio
from pathlib import Path
from loguru import logger

# 添加项目根目录到Python路径
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neo4j import AsyncGraphDatabase
from config.settings import get_settings


async def cleanup_neo4j_database():
    """清理neo4j数据库，只保留NotionPage和SyncMetadata节点"""
    
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    
    settings = get_settings()
    
    logger.info("="*50)
    logger.info("🧹 清理被污染的neo4j数据库")
    logger.info("="*50)
    
    try:
        # 连接到neo4j数据库
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password)
        )
        
        async with driver.session() as session:
            # 1. 查看当前数据库状态
            logger.info("📊 查看当前数据库状态...")
            result = await session.run("""
                MATCH (n) 
                RETURN labels(n) as labels, count(n) as count
                ORDER BY count DESC
            """)
            records = await result.data()
            
            logger.info("当前节点类型和数量:")
            for record in records:
                labels = record['labels']
                count = record['count']
                logger.info(f"  {labels}: {count}")
            
            # 2. 删除所有测试节点和非法节点
            logger.info("🗑️ 删除测试节点和污染节点...")
            
            # 删除测试节点
            await session.run("MATCH (n) WHERE n.name CONTAINS 'Test' DETACH DELETE n")
            logger.info("✅ 删除了测试节点")
            
            # 删除WechatPerson节点
            await session.run("MATCH (n:WechatPerson) DETACH DELETE n")
            logger.info("✅ 删除了WechatPerson节点")
            
            # 删除所有Graphiti相关节点（除了NotionPage和SyncMetadata）
            await session.run("""
                MATCH (n) 
                WHERE NOT 'NotionPage' IN labels(n) 
                AND NOT 'SyncMetadata' IN labels(n)
                DETACH DELETE n
            """)
            logger.info("✅ 删除了所有非NotionPage和SyncMetadata节点")
            
            # 3. 清理孤立的关系
            await session.run("MATCH ()-[r]->() WHERE startNode(r) IS NULL OR endNode(r) IS NULL DELETE r")
            logger.info("✅ 清理了孤立的关系")
            
            # 4. 查看清理后的状态
            logger.info("📊 查看清理后的数据库状态...")
            result = await session.run("""
                MATCH (n) 
                RETURN labels(n) as labels, count(n) as count
                ORDER BY count DESC
            """)
            records = await result.data()
            
            logger.info("清理后的节点类型和数量:")
            for record in records:
                labels = record['labels']
                count = record['count']
                logger.info(f"  {labels}: {count}")
            
            # 5. 验证只剩下NotionPage和SyncMetadata
            result = await session.run("""
                MATCH (n) 
                WHERE NOT 'NotionPage' IN labels(n) 
                AND NOT 'SyncMetadata' IN labels(n)
                RETURN count(n) as invalid_count
            """)
            record = await result.single()
            invalid_count = record['invalid_count']
            
            if invalid_count == 0:
                logger.info("✅ 数据库已恢复到原始状态，只包含NotionPage和SyncMetadata节点")
            else:
                logger.warning(f"⚠️ 仍有 {invalid_count} 个无效节点")
        
        await driver.close()
        logger.info("✅ 数据库清理完成")
        
    except Exception as e:
        logger.error(f"❌ 数据库清理失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(cleanup_neo4j_database())