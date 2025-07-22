#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chimera 强制全量同步脚本
专门用于手动执行强制全量同步
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.logging import setup_logging
from config.settings import get_settings
from sync_service.sync_service import SyncService
from loguru import logger


async def run_force_full_sync():
    """强制执行全量同步（清空Neo4j数据后重新同步）"""
    logger.info("🧹 强制全量同步：清空Neo4j数据...")
    
    from core.graphiti_client import GraphitiClient
    
    # 清空Neo4j数据
    graph_client = GraphitiClient()
    try:
        await graph_client.initialize()
        
        # 删除所有NotionPage节点和SyncMetadata
        clear_queries = [
            "MATCH (n:NotionPage) DETACH DELETE n",
            "MATCH (m:SyncMetadata) DELETE m"
        ]
        
        async with graph_client._driver.session() as session:
            for query in clear_queries:
                result = await session.run(query)
                summary = await result.consume()
                logger.info(f"清理完成：删除了 {summary.counters.nodes_deleted} 个节点")
        
        await graph_client.close()
        logger.info("🧹 Neo4j数据已清空")
        
    except Exception as e:
        logger.error(f"❌ 清空Neo4j数据失败: {e}")
        return False
    
    # 现在运行同步（将触发全量同步）
    logger.info("🔄 开始全量同步...")
    sync_service = SyncService()
    try:
        await sync_service.initialize()
        success = await sync_service.run_manual_sync()
        if success:
            logger.info("✅ 强制全量同步完成")
            return True
        else:
            logger.error("❌ 强制全量同步失败")
            return False
    finally:
        await sync_service.stop()


def main():
    """主函数"""
    # 设置日志
    setup_logging()
    
    # 显示标题
    logger.info("=" * 50)
    logger.info("🔧 Chimera 强制全量同步工具")
    logger.info("=" * 50)
    
    # 检查配置
    settings = get_settings()
    logger.info(f"配置: Neo4j URI: {settings.neo4j_uri}")
    
    # 执行强制全量同步
    try:
        success = asyncio.run(run_force_full_sync())
        if success:
            logger.info("✅ 操作完成")
            sys.exit(0)
        else:
            logger.error("❌ 操作失败")
            sys.exit(1)
    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()