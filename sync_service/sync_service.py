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
                
                # Get last sync time (but use None if scanner was reset)
                if self.scanner._last_scan_time is None:
                    last_sync_time = None  # Force full sync
                    logger.info("Scanner was reset, performing full sync")
                else:
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
                
                # Update last sync time
                await self._update_last_sync_time()
                
                logger.info("Sync cycle completed successfully")
                return True
                
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