#!/usr/bin/env python3
"""
The Archivist - Background Sync Service
Main entry point for the sync service that monitors Notion and updates the graph.
"""

import asyncio
import signal
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from loguru import logger

from config.settings import get_settings
from config.logging import setup_logging, LogExecutionTime
from core.notion_client import NotionExtractor
from core.graphiti_client import GraphitiClient
from .notion_scanner import NotionScanner
from .graph_updater import GraphUpdater
from .scheduler import SyncScheduler


class SyncService:
    """
    Main sync service that coordinates the entire sync process.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.running = False
        self.notion_client = None
        self.graph_client = None
        self.scanner = None
        self.updater = None
        self.scheduler = None
        self._last_full_sync_time = None
        
    async def initialize(self):
        """Initialize all components of the sync service."""
        logger.info("Initializing sync service...")
        
        # Initialize clients
        self.notion_client = NotionExtractor(
            api_key=self.settings.notion_token,
            rate_limit_per_second=self.settings.notion_rate_limit_per_second
        )
        
        self.graph_client = GraphitiClient(
            neo4j_uri=self.settings.neo4j_uri,
            neo4j_user=self.settings.neo4j_username,
            neo4j_password=self.settings.neo4j_password
        )
        
        # Initialize service components
        self.scanner = NotionScanner(self.notion_client)
        self.updater = GraphUpdater(self.graph_client, self.notion_client)
        self.scheduler = SyncScheduler(
            sync_interval_minutes=self.settings.sync_interval_minutes,
            sync_callback=self.run_sync_cycle
        )
        
        # Initialize graph client
        await self.graph_client.initialize()
        
        logger.info("Sync service initialized successfully")
    
    async def run_sync_cycle(self) -> bool:
        """
        Run a complete sync cycle.
        决定执行全量同步或增量同步的策略：
        - 首次运行：全量同步
        - 距离上次全量同步超过3天：全量同步
        - 北京时间凌晨4点定时全量同步（距离上次全量同步超过1天）
        - 其他情况：增量同步
        
        Returns:
            True if sync was successful, False otherwise
        """
        logger.info("Starting sync cycle...")
        
        try:
            with LogExecutionTime("sync_cycle"):
                # Check health of both services
                if not await self._health_check():
                    logger.error("Health check failed, skipping sync cycle")
                    return False
                
                # 判断是否需要全量同步
                should_do_full_sync = await self._should_do_full_sync()
                
                if should_do_full_sync:
                    logger.info("🔄 执行全量同步 (清空数据库后重新构建图谱)")
                    success = await self._run_full_sync()
                else:
                    logger.info("⚡ 执行增量同步")
                    success = await self._run_incremental_sync()
                
                if success:
                    # Update last sync time
                    await self._update_last_sync_time()
                    
                    # 如果是全量同步，更新全量同步时间
                    if should_do_full_sync:
                        await self._update_last_full_sync_time()
                    
                    logger.info("Sync cycle completed successfully")
                else:
                    logger.error("Sync cycle failed")
                
                return success
                
        except Exception as e:
            logger.exception(f"Sync cycle failed: {e}")
            return False
    
    async def _health_check(self) -> bool:
        """Check health of Notion API and Graph database."""
        try:
            notion_healthy = await self.notion_client.health_check()
            graph_healthy = await self.graph_client.health_check()
            
            if not notion_healthy:
                logger.error("Notion API health check failed")
            if not graph_healthy:
                logger.error("Graph database health check failed")
            
            return notion_healthy and graph_healthy
            
        except Exception as e:
            logger.exception(f"Health check failed: {e}")
            return False
    
    async def _get_last_sync_time(self) -> Optional[datetime]:
        """Get the last sync time from the graph database."""
        try:
            # Query for sync metadata
            query = """
            MATCH (meta:SyncMetadata)
            RETURN meta.last_sync_time as last_sync_time
            ORDER BY meta.last_sync_time DESC
            LIMIT 1
            """
            
            async with self.graph_client._driver.session() as session:
                result = await session.run(query)
                record = await result.single()
                if record:
                    return record["last_sync_time"]
            
            return None
            
        except Exception as e:
            logger.warning(f"Could not get last sync time: {e}")
            return None
    
    async def _update_last_sync_time(self):
        """Update the last sync time in the graph database."""
        try:
            query = """
            MERGE (meta:SyncMetadata {id: 'main'})
            SET meta.last_sync_time = datetime()
            """
            
            async with self.graph_client._driver.session() as session:
                await session.run(query)
            
        except Exception as e:
            logger.warning(f"Could not update last sync time: {e}")
    
    async def _get_last_full_sync_time(self) -> Optional[datetime]:
        """Get the last full sync time from the graph database."""
        try:
            query = """
            MATCH (meta:SyncMetadata {id: 'main'})
            RETURN meta.last_full_sync_time as last_full_sync_time
            """
            
            async with self.graph_client._driver.session() as session:
                result = await session.run(query)
                record = await result.single()
                if record and record["last_full_sync_time"]:
                    return record["last_full_sync_time"]
            
            return None
            
        except Exception as e:
            logger.warning(f"Could not get last full sync time: {e}")
            return None
    
    async def _update_last_full_sync_time(self):
        """Update the last full sync time in the graph database."""
        try:
            query = """
            MERGE (meta:SyncMetadata {id: 'main'})
            SET meta.last_full_sync_time = datetime()
            """
            
            async with self.graph_client._driver.session() as session:
                await session.run(query)
            
        except Exception as e:
            logger.warning(f"Could not update last full sync time: {e}")
    
    async def _should_do_full_sync(self) -> bool:
        """判断是否应该执行全量同步"""
        # 检查是否为首次运行程序（检查Neo4j中是否有任何NotionPage）
        is_first_run = await self._is_first_run()
        if is_first_run:
            logger.info("🆕 首次运行程序，Neo4j中没有任何页面数据，执行全量同步")
            return True
        
        # 获取上次全量同步时间
        last_full_sync = await self._get_last_full_sync_time()
        
        if last_full_sync is None:
            logger.info("🆕 没有全量同步记录，需要全量同步")
            return True
        
        # 检查是否超过12小时 (处理Neo4j DateTime类型和时区问题)
        if hasattr(last_full_sync, 'to_native'):
            # Neo4j DateTime转换为Python datetime
            last_full_sync_native = last_full_sync.to_native()
        else:
            last_full_sync_native = last_full_sync
        
        # 确保两个datetime对象具有相同的时区信息
        from datetime import timezone
        now = datetime.now(timezone.utc)
        if last_full_sync_native.tzinfo is None:
            # 如果数据库时间没有时区，假设是UTC
            last_full_sync_native = last_full_sync_native.replace(tzinfo=timezone.utc)
        
        # 检查是否需要全量同步（3天一次，北京时间凌晨4点）
        days_since_last_full = (now - last_full_sync_native).total_seconds() / (24 * 3600)
        
        # 如果距离上次全量同步超过3天，需要全量同步
        if days_since_last_full >= 3:
            logger.info(f"⏰ 距离上次全量同步已过 {days_since_last_full:.1f} 天，需要全量同步")
            return True
        
        # 检查是否是北京时间凌晨4点（允许在4:00-4:30之间执行）
        from datetime import timezone, timedelta
        beijing_tz = timezone(timedelta(hours=8))
        beijing_now = now.astimezone(beijing_tz)
        current_hour = beijing_now.hour
        current_minute = beijing_now.minute
        
        # 如果距离上次全量同步超过1天，且当前是北京时间凌晨4点
        if days_since_last_full >= 1 and current_hour == 4 and current_minute < 30:
            logger.info(f"🌙 北京时间凌晨4点定时全量同步 (距离上次 {days_since_last_full:.1f} 天)")
            return True
        
        logger.info(f"⚡ 距离上次全量同步 {days_since_last_full:.1f} 天，执行增量同步")
        return False
    
    async def _is_first_run(self) -> bool:
        """检查是否为首次运行（Neo4j中是否有任何NotionPage数据）"""
        try:
            query = "MATCH (n:NotionPage) RETURN count(n) as page_count LIMIT 1"
            async with self.graph_client._driver.session() as session:
                result = await session.run(query)
                record = await result.single()
                page_count = record["page_count"] if record else 0
                return page_count == 0
        except Exception as e:
            logger.warning(f"检查首次运行状态失败，默认为首次运行: {e}")
            return True
    
    async def _run_full_sync(self) -> bool:
        """执行全量同步，先清空Neo4j数据后重新同步（与--force-full-sync逻辑一致）"""
        try:
            # 1. 清空Neo4j数据（与--force-full-sync保持一致）
            logger.info("🧹 清空Neo4j数据...")
            clear_queries = [
                "MATCH (n:NotionPage) DETACH DELETE n",
                "MATCH (m:SyncMetadata) DELETE m"
            ]
            
            async with self.graph_client._driver.session() as session:
                for query in clear_queries:
                    result = await session.run(query)
                    summary = await result.consume()
                    logger.info(f"清理完成：删除了 {summary.counters.nodes_deleted} 个节点")
            
            logger.info("🧹 Neo4j数据已清空")
            
            # 2. 获取所有Notion页面
            logger.info("获取所有Notion页面...")
            changed_pages = await self.scanner.scan_for_changes(None)  # None表示全量扫描
            
            # 3. 更新图数据库（由于已清空，这里是全新构建）
            if changed_pages:
                logger.info(f"构建 {len(changed_pages)} 个页面到图数据库...")
                sync_report = await self.updater.update_graph(changed_pages)
                self._log_sync_results(sync_report)
            else:
                logger.info("没有发现任何页面")
            
            return True
            
        except Exception as e:
            logger.exception(f"全量同步失败: {e}")
            return False
    
    async def _run_incremental_sync(self) -> bool:
        """执行增量同步"""
        try:
            # Get last sync time
            last_sync_time = await self._get_last_sync_time()
            
            # Scan for changed pages
            changed_pages = await self.scanner.scan_for_changes(last_sync_time)
            
            if not changed_pages:
                logger.info("No changes detected, sync cycle complete")
                return True
            
            logger.info(f"Found {len(changed_pages)} pages to sync")
            
            # Update graph with changes
            sync_report = await self.updater.update_graph(changed_pages)
            
            # Log sync results
            self._log_sync_results(sync_report)
            
            return True
            
        except Exception as e:
            logger.exception(f"增量同步失败: {e}")
            return False
    
    async def _cleanup_deleted_pages(self, current_pages):
        """清理已删除的页面"""
        try:
            # 获取当前Notion页面ID集合
            current_page_ids = set(page.notion_id for page in current_pages)
            
            # 获取Neo4j中的所有页面ID
            query = "MATCH (n:NotionPage) RETURN collect(n.notionId) as page_ids"
            async with self.graph_client._driver.session() as session:
                result = await session.run(query)
                record = await result.single()
                graph_page_ids = set(record["page_ids"] if record else [])
            
            # 找出需要删除的页面
            deleted_page_ids = graph_page_ids - current_page_ids
            
            if deleted_page_ids:
                logger.info(f"🗑️ 发现 {len(deleted_page_ids)} 个已删除页面，开始清理...")
                
                # 从Neo4j删除
                delete_query = """
                MATCH (n:NotionPage) 
                WHERE n.notionId IN $page_ids
                DETACH DELETE n
                """
                
                async with self.graph_client._driver.session() as session:
                    result = await session.run(delete_query, page_ids=list(deleted_page_ids))
                    summary = await result.consume()
                    
                    logger.info(f"✅ 已从Neo4j删除 {summary.counters.nodes_deleted} 个失效页面")
            else:
                logger.info("✅ 没有发现需要删除的页面")
                
        except Exception as e:
            logger.warning(f"⚠️ 清理删除页面失败: {e}")
    
    def _log_sync_results(self, sync_report):
        """Log the results of the sync operation."""
        logger.info(f"Sync completed: {sync_report.status}")
        logger.info(f"Pages processed: {sync_report.pages_processed}")
        logger.info(f"Pages created: {sync_report.pages_created}")
        logger.info(f"Pages updated: {sync_report.pages_updated}")
        logger.info(f"Pages deleted: {sync_report.pages_deleted}")
        logger.info(f"Relationships created: {sync_report.relationships_created}")
        logger.info(f"Relationships updated: {sync_report.relationships_updated}")
        logger.info(f"Relationships deleted: {sync_report.relationships_deleted}")
        
        if sync_report.errors:
            logger.warning(f"Errors during sync: {len(sync_report.errors)}")
            for error in sync_report.errors[:5]:  # Log first 5 errors
                logger.warning(f"Sync error: {error}")
    
    async def run_manual_sync(self):
        """Run a manual sync cycle."""
        logger.info("Starting manual sync...")
        success = await self.run_sync_cycle()
        if success:
            logger.info("Manual sync completed successfully")
        else:
            logger.error("Manual sync failed")
        return success
    
    async def start(self):
        """Start the sync service."""
        if self.running:
            logger.warning("Sync service is already running")
            return
        
        logger.info("Starting sync service...")
        self.running = True
        
        # Start scheduler
        await self.scheduler.start()
        
        logger.info("Sync service started successfully")
        
        # Keep the service running
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, stopping...")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the sync service."""
        if not self.running:
            return
        
        logger.info("Stopping sync service...")
        self.running = False
        
        # Stop scheduler
        if self.scheduler:
            await self.scheduler.stop()
        
        # Close clients
        if self.graph_client:
            await self.graph_client.close()
        
        logger.info("Sync service stopped")
    
    async def get_stats(self):
        """Get sync service statistics."""
        if not self.graph_client:
            return {"error": "Graph client not initialized"}
        
        try:
            stats = await self.graph_client.get_graph_stats()
            return stats.dict()
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}


async def main():
    """Main entry point for the sync service."""
    # Setup logging
    setup_logging()
    
    # Create sync service
    sync_service = SyncService()
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(sync_service.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Initialize and start service
        await sync_service.initialize()
        await sync_service.start()
        
    except Exception as e:
        logger.exception(f"Fatal error in sync service: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())