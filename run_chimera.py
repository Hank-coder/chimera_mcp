#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chimera 同步服务启动脚本
专门用于启动15分钟定期同步监测
"""

import asyncio
import sys
import argparse
from pathlib import Path

from sync_service.sync_service import SyncService

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


from config.logging import setup_logging
from config.settings import get_settings
from loguru import logger


async def generate_cache():
    """生成JSON缓存文件（简化版本，不再处理删除检测）"""
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
            paths.append({
                "path_string": path_string,
                "path_titles": path_titles,
                "path_ids": path_ids,
                "leaf_id": leaf_id,
                "leaf_title": pages_map[leaf_id]["title"],
                "path_length": len(path_ids) - 1
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


async def run_continuous_sync():
    """运行持续的同步监测"""
    settings = get_settings()
    sync_interval = settings.sync_interval_minutes
    
    logger.info(f"🔄 启动{sync_interval}分钟同步监测服务...")
    
    sync_service = SyncService()
    sync_cycle_count = 0
    
    try:
        await sync_service.initialize()
        logger.info(f"✅ 同步服务已启动，每{sync_interval}分钟检查更新")
        
        while True:
            try:
                logger.info("🔍 开始检查Notion更新...")
                success = await sync_service.run_manual_sync()
                
                if success:
                    logger.info("✅ 同步检查完成")
                    # 生成JSON缓存
                    await generate_cache()
                else:
                    logger.warning("⚠️ 同步检查发现问题")
                
                sync_cycle_count += 1

                # 等待配置的时间间隔
                logger.info(f"⏳ 等待{sync_interval}分钟后进行下次检查...")
                await asyncio.sleep(sync_interval * 60)
                    
            except Exception as e:
                logger.exception(f"❌ 同步监测异常: {e}")
                # 遇到异常等待5分钟后重试
                logger.info("⏳ 等待5分钟后重试...")
                await asyncio.sleep(5 * 60)
                
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止...")
    finally:
        await sync_service.stop()
        logger.info("✅ 同步服务已停止")


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
            sys.exit(1)
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
        return
    
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
        else:
            logger.error("❌ 强制全量同步失败")
            sys.exit(1)
    finally:
        await sync_service.stop()


async def show_status():
    """显示系统状态"""
    logger.info("📊 检查系统状态...")
    
    try:
        sync_service = SyncService()
        await sync_service.initialize()
        
        stats = await sync_service.get_stats()
        logger.info(f"同步服务状态: {stats}")
        
        await sync_service.stop()
        
    except Exception as e:
        logger.error(f"无法获取状态: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Chimera 同步服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python run_chimera.py                    # 运行15分钟持续同步监测
  python run_chimera.py --manual-sync      # 执行一次手动同步
  python run_chimera.py --status           # 显示系统状态
  python run_chimera.py --generate-cache   # 生成JSON缓存文件
  python run_chimera.py --force-full-sync  # 强制全量同步（测试首次运行）

注意: MCP服务器请单独运行：
  python fastmcp_server.py --port 3000
        """
    )
    
    parser.add_argument(
        "--manual-sync", 
        action="store_true",
        help="执行一次手动同步"
    )
    
    parser.add_argument(
        "--status", 
        action="store_true",
        help="显示系统状态"
    )
    
    parser.add_argument(
        "--debug", 
        action="store_true",
        help="启用调试模式"
    )
    
    parser.add_argument(
        "--generate-cache", 
        action="store_true",
        help="生成JSON缓存文件"
    )
    
    parser.add_argument(
        "--force-full-sync", 
        action="store_true",
        help="强制执行全量同步（清空Neo4j数据后重新同步）"
    )
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging()
    
    # 显示欢迎信息
    logger.info("=" * 60)
    logger.info("🔄 Chimera 同步服务")
    logger.info("=" * 60)
    
    # 检查配置
    settings = get_settings()
    if args.debug:
        logger.info(f"配置: Neo4j URI: {settings.neo4j_uri}")
    
    # 根据参数运行相应的功能
    try:
        if args.manual_sync:
            asyncio.run(run_manual_sync())
        elif args.status:
            asyncio.run(show_status())
        elif args.generate_cache:
            asyncio.run(generate_cache())
        elif args.force_full_sync:
            asyncio.run(run_force_full_sync())
        else:
            # 默认运行持续同步
            asyncio.run(run_continuous_sync())
            
    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()