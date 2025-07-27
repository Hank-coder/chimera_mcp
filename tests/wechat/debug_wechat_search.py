#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信关系搜索调试脚本
用于诊断和修复搜索功能问题
"""

import asyncio
import sys
from pathlib import Path
from loguru import logger

# 确保项目根目录在Python路径中
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.wechat_graphiti_client import WeChatGraphitiClient
from config.settings import get_settings
from neo4j import AsyncGraphDatabase


async def debug_database_connection():
    """调试数据库连接"""
    settings = get_settings()
    
    logger.info("=== 调试数据库连接 ===")
    
    try:
        # 测试Neo4j连接
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password)
        )
        
        async with driver.session() as session:
            # 检查Entity节点数量
            result = await session.run("MATCH (n:Entity) RETURN count(n) as count")
            entity_count = await result.single()
            logger.info(f"Entity节点数量: {entity_count['count']}")
            
            # 检查Episodic节点数量
            result = await session.run("MATCH (n:Episodic) RETURN count(n) as count")
            episodic_count = await result.single()
            logger.info(f"Episodic节点数量: {episodic_count['count']}")
            
            # 检查所有节点标签
            result = await session.run("CALL db.labels()")
            labels = [record["label"] async for record in result]
            logger.info(f"所有节点标签: {labels}")
            
            # 检查关系类型
            result = await session.run("CALL db.relationshipTypes()")
            relationships = [record["relationshipType"] async for record in result]
            logger.info(f"所有关系类型: {relationships}")
            
            # 查看一些Entity节点样例
            result = await session.run("MATCH (n:Entity) RETURN n.name, n.summary LIMIT 10")
            entities = [(record["n.name"], record["n.summary"]) async for record in result]
            logger.info(f"Entity节点样例: {entities}")
            
        await driver.close()
        logger.info("数据库连接测试完成")
        return True
        
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        return False


async def debug_basic_search():
    """调试基础搜索功能"""
    logger.info("=== 调试基础搜索功能 ===")
    
    try:
        # 创建客户端
        client = WeChatGraphitiClient(use_2_0_flash=True)
        await client.initialize()
        
        # 测试基础搜索
        test_queries = ["肥猫", "GREEN", "项目", "敏哥"]
        
        for query in test_queries:
            logger.info(f"\n测试查询: '{query}'")
            
            try:
                # 使用简单的搜索方法
                search_results = await client.graphiti.search(
                    query=query,
                    num_results=5
                )
                
                logger.info(f"简单搜索结果数量: {len(search_results)}")
                
                for i, result in enumerate(search_results):
                    logger.info(f"结果 {i+1}: {result}")
                    
            except Exception as e:
                logger.error(f"搜索 '{query}' 失败: {e}")
        
        await client.close()
        
    except Exception as e:
        logger.error(f"基础搜索测试失败: {e}")


async def debug_advanced_search():
    """调试高级搜索功能"""
    logger.info("=== 调试高级搜索功能 ===")
    
    try:
        from graphiti_core.search.search_config_recipes import (
            NODE_HYBRID_SEARCH_RRF,
            COMBINED_HYBRID_SEARCH_CROSS_ENCODER
        )
        from graphiti_core.search.search_filters import SearchFilters
        
        client = WeChatGraphitiClient(use_2_0_flash=True)
        await client.initialize()
        
        # 创建搜索过滤器
        search_filter = SearchFilters(
            node_labels=["Entity"]
        )
        
        test_queries = ["肥猫", "GREEN"]
        
        for query in test_queries:
            logger.info(f"\n高级搜索测试: '{query}'")
            
            try:
                # 使用高级搜索配置
                config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                config.limit = 10
                
                search_results = await client.graphiti.search_(
                    query=query,
                    config=config,
                    search_filter=search_filter
                )
                
                logger.info(f"高级搜索结果: 节点={len(search_results.nodes)}, 边={len(search_results.edges)}")
                
                # 显示节点详情
                for i, node in enumerate(search_results.nodes[:5]):
                    logger.info(f"节点 {i+1}: name='{getattr(node, 'name', 'N/A')}', summary='{getattr(node, 'summary', 'N/A')[:100]}'")
                
                # 显示边详情
                for i, edge in enumerate(search_results.edges[:3]):
                    logger.info(f"边 {i+1}: fact='{getattr(edge, 'fact', 'N/A')[:100]}'")
                    
            except Exception as e:
                logger.error(f"高级搜索 '{query}' 失败: {e}")
        
        await client.close()
        
    except Exception as e:
        logger.error(f"高级搜索测试失败: {e}")


async def main():
    """主调试函数"""
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    
    logger.info("开始微信关系搜索调试...")
    
    # 1. 测试数据库连接
    db_ok = await debug_database_connection()
    if not db_ok:
        logger.error("数据库连接失败，无法继续测试")
        return
    
    # 2. 测试基础搜索
    await debug_basic_search()
    
    # 3. 测试高级搜索
    await debug_advanced_search()
    
    logger.info("调试完成")


if __name__ == "__main__":
    asyncio.run(main())