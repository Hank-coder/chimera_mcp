#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chimera 手动同步脚本
专门用于手动全量同步和维护操作
"""

import asyncio
import sys
import argparse
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.logging import setup_logging
from config.settings import get_settings
from sync_service.sync_service import SyncService
from loguru import logger


async def generate_cache():
    """生成JSON缓存文件"""
    import json
    from pathlib import Path
    from datetime import datetime
    from core.graphiti_client import GraphitiClient
    
    try:
        logger.info("📄 生成JSON缓存...")
        
        graph_client = GraphitiClient()
        await graph_client.initialize()
        
        # 生成缓存数据
        cache_data = await _build_cache_data(graph_client)
        
        # 写入缓存文件
        cache_dir = Path("llm_cache")
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / "chimera_cache.json"
        
        _write_cache_file(cache_file, cache_data)
        
        await graph_client.close()
        
        logger.info(f"✅ 缓存完成：{cache_data['metadata']['total_pages']} 页面，{cache_data['metadata']['total_paths']} 路径")
        return True
        
    except Exception as e:
        logger.error(f"❌ 缓存生成失败: {e}")
        return False


async def _build_cache_data(graph_client):
    """构建缓存数据"""
    from datetime import datetime
    
    # 查询所有页面和关系
    query = """
    MATCH (p:NotionPage)
    OPTIONAL MATCH (p)-[:CHILD_OF]->(parent:NotionPage)
    OPTIONAL MATCH (child:NotionPage)-[:CHILD_OF]->(p)
    RETURN p {
        .notionId,
        .title,
        .type,
        .tags,
        .lastEditedTime,
        .url,
        .level
    } as page,
    parent.notionId as parent_id,
    collect(DISTINCT child.notionId) as children_ids
    """
    
    cache_data = {
        "generated_at": datetime.now().isoformat(),
        "pages": {},
        "paths": [],
        "metadata": {"total_pages": 0, "total_paths": 0}
    }
    
    pages_map = {}
    
    async with graph_client._driver.session() as session:
        result = await session.run(query)
        
        async for record in result:
            page = record["page"]
            parent_id = record["parent_id"]
            children_ids = record["children_ids"] or []
            
            # 处理DateTime序列化
            last_edited = page["lastEditedTime"]
            if hasattr(last_edited, 'isoformat'):
                last_edited = last_edited.isoformat()
            elif last_edited:
                last_edited = str(last_edited)
            
            cache_data["pages"][page["notionId"]] = {
                "title": page["title"],
                "type": page["type"],
                "tags": page["tags"] or [],
                "lastEditedTime": last_edited,
                "url": page["url"],
                "level": page.get("level", 0),
                "parent_id": parent_id,
                "children_ids": children_ids
            }
            pages_map[page["notionId"]] = cache_data["pages"][page["notionId"]]
    
    # 构建路径
    cache_data["paths"] = _build_paths(pages_map)
    cache_data["metadata"]["total_pages"] = len(cache_data["pages"])
    cache_data["metadata"]["total_paths"] = len(cache_data["paths"])
    
    return cache_data


def _build_paths(pages_map):
    """构建完整路径"""
    paths = []
    
    # 找到所有叶子节点
    leaf_nodes = [pid for pid, page in pages_map.items() if not page["children_ids"]]
    
    for leaf_id in leaf_nodes:
        # 从叶子节点向上构建路径
        path_ids = []
        path_titles = []
        current_id = leaf_id
        
        while current_id and current_id in pages_map:
            page = pages_map[current_id]
            path_ids.insert(0, current_id)
            path_titles.insert(0, page["title"])
            current_id = page["parent_id"]
        
        if len(path_ids) > 0:
            path_string = " -> ".join(path_titles)
            actual_path_length = len(path_ids) - 1
            paths.append({
                "path_string": path_string,
                "path_titles": path_titles,
                "path_ids": path_ids,
                "leaf_id": leaf_id,
                "leaf_title": pages_map[leaf_id]["title"],
                "leaf_last_edited_time": pages_map[leaf_id]["lastEditedTime"],
                "path_length": actual_path_length
            })
    
    return paths


def _write_cache_file(cache_file, cache_data):
    """写入缓存文件"""
    import json
    
    def json_encoder(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        elif hasattr(obj, '__dict__'):
            return str(obj)
        return obj
    
    # 原子写入
    temp_file = cache_file.with_suffix('.tmp')
    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2, default=json_encoder)
    
    temp_file.replace(cache_file)


async def run_manual_sync():
    """运行一次性手动同步"""
    logger.info("⚡ 执行手动同步...")
    sync_service = SyncService()
    try:
        await sync_service.initialize()
        success = await sync_service.run_manual_sync()
        if success:
            logger.info("✅ 手动同步完成")
            # 生成JSON缓存
            await generate_cache()
        else:
            logger.error("❌ 手动同步失败")
            return False
        return True
    finally:
        await sync_service.stop()


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
            # 生成JSON缓存
            await generate_cache()
            return True
        else:
            logger.error("❌ 强制全量同步失败")
            return False
    finally:
        await sync_service.stop()


async def show_stats():
    """显示Neo4j数据库统计信息"""
    logger.info("📊 检查Neo4j数据库统计...")
    
    try:
        from core.graphiti_client import GraphitiClient
        graph_client = GraphitiClient()
        await graph_client.initialize()
        
        stats_query = """
        CALL {
            MATCH (p:NotionPage) RETURN count(p) as pages
        }
        CALL {
            MATCH ()-[r:CHILD_OF]->() RETURN count(r) as child_relations
        }
        CALL {
            MATCH ()-[r:HAS_TAG]->() RETURN count(r) as tag_relations
        }
        RETURN pages, child_relations, tag_relations
        """
        
        async with graph_client._driver.session() as session:
            result = await session.run(stats_query)
            record = await result.single()
            
            if record:
                logger.info(f"📄 总页面数: {record['pages']}")
                logger.info(f"🔗 父子关系数: {record['child_relations']}")
                logger.info(f"🏷️  标签关系数: {record['tag_relations']}")
            else:
                logger.info("📊 未找到统计数据")
        
        await graph_client.close()
        return True
        
    except Exception as e:
        logger.error(f"无法获取统计信息: {e}")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Chimera 手动同步和维护工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python manual_sync.py --sync              # 执行一次手动同步
  python manual_sync.py --full-sync         # 强制全量同步（清空后重建）
  python manual_sync.py --generate-cache    # 仅生成JSON缓存
  python manual_sync.py --stats             # 显示数据库统计信息

注意: 
- 手动同步用于测试或维护
- 生产环境应使用 webhook_server.py 进行实时同步
- MCP服务器请单独运行：python fastmcp_server.py
        """
    )
    
    parser.add_argument(
        "--sync", 
        action="store_true",
        help="执行一次手动同步"
    )
    
    parser.add_argument(
        "--full-sync", 
        action="store_true",
        help="强制执行全量同步（清空Neo4j数据后重新同步）"
    )
    
    parser.add_argument(
        "--generate-cache", 
        action="store_true",
        help="生成JSON缓存文件"
    )
    
    parser.add_argument(
        "--stats", 
        action="store_true",
        help="显示Neo4j数据库统计信息"
    )
    
    parser.add_argument(
        "--debug", 
        action="store_true",
        help="启用调试模式"
    )
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging()
    
    # 显示标题
    logger.info("=" * 50)
    logger.info("🔧 Chimera 手动同步工具")
    logger.info("=" * 50)
    
    # 检查参数
    if not any([args.sync, args.full_sync, args.generate_cache, args.stats]):
        logger.error("❌ 请指定操作参数，使用 --help 查看帮助")
        sys.exit(1)
    
    # 检查配置
    settings = get_settings()
    if args.debug:
        logger.info(f"配置: Neo4j URI: {settings.neo4j_uri}")
    
    # 根据参数运行相应的功能
    success = True
    try:
        if args.sync:
            success = asyncio.run(run_manual_sync())
        elif args.full_sync:
            success = asyncio.run(run_force_full_sync())
        elif args.generate_cache:
            success = asyncio.run(generate_cache())
        elif args.stats:
            success = asyncio.run(show_stats())
            
    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        success = False
    
    if success:
        logger.info("✅ 操作完成")
        sys.exit(0)
    else:
        logger.error("❌ 操作失败")
        sys.exit(1)


if __name__ == "__main__":
    main()