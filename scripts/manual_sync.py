#!/usr/bin/env python3
"""
Manual Sync Script
Triggers a manual sync operation for testing and maintenance.
"""

import asyncio
import argparse
import sys
from datetime import datetime, timedelta
from loguru import logger

from config.settings import get_settings
from config.logging import setup_logging
from sync_service.main import SyncService


async def run_manual_sync(full_sync: bool = False, page_ids: list = None):
    """
    Run a manual sync operation.
    
    Args:
        full_sync: Whether to perform a full sync
        page_ids: Specific page IDs to sync (optional)
    """
    logger.info("Starting manual sync...")
    
    sync_service = SyncService()
    
    try:
        # Initialize the sync service
        await sync_service.initialize()
        
        if page_ids:
            logger.info(f"Syncing specific pages: {page_ids}")
            # This would require additional implementation in the sync service
            # For now, we'll just run a regular sync
            success = await sync_service.run_manual_sync()
        elif full_sync:
            logger.info("Performing full sync...")
            # Reset sync state to force full sync
            if sync_service.scanner:
                sync_service.scanner.reset_scan_state()
            success = await sync_service.run_manual_sync()
        else:
            logger.info("Performing incremental sync...")
            success = await sync_service.run_manual_sync()
        
        if success:
            logger.info("Manual sync completed successfully")
            
            # Get and display stats
            stats = await sync_service.get_stats()
            if "error" not in stats:
                logger.info(f"Total pages in graph: {stats.get('total_pages', 0)}")
                logger.info(f"Total relationships: {stats.get('total_relationships', 0)}")
            
        else:
            logger.error("Manual sync failed")
            sys.exit(1)
            
    except Exception as e:
        logger.exception(f"Manual sync failed with exception: {e}")
        sys.exit(1)
    finally:
        await sync_service.stop()


async def sync_stats():
    """Display sync statistics."""
    logger.info("Getting sync statistics...")
    
    sync_service = SyncService()
    
    try:
        await sync_service.initialize()
        
        stats = await sync_service.get_stats()
        
        if "error" in stats:
            logger.error(f"Error getting stats: {stats['error']}")
            return
        
        print("\n=== Sync Statistics ===")
        print(f"Total pages: {stats.get('total_pages', 0)}")
        print(f"Total relationships: {stats.get('total_relationships', 0)}")
        
        rel_counts = stats.get('relationship_counts', {})
        if rel_counts:
            print("\nRelationship counts:")
            for rel_type, count in rel_counts.items():
                print(f"  {rel_type}: {count}")
        
        most_connected = stats.get('most_connected_pages', [])
        if most_connected:
            print("\nMost connected pages:")
            for page in most_connected[:5]:
                print(f"  {page.get('title', 'Unknown')}: {page.get('connections', 0)} connections")
        
        last_sync = stats.get('last_sync')
        if last_sync:
            print(f"\nLast sync: {last_sync}")
        
    except Exception as e:
        logger.exception(f"Error getting stats: {e}")
    finally:
        await sync_service.stop()


async def health_check():
    """Perform a health check on sync components."""
    logger.info("Performing health check...")
    
    sync_service = SyncService()
    
    try:
        await sync_service.initialize()
        
        # Check Notion API
        notion_healthy = await sync_service.notion_client.health_check()
        print(f"Notion API: {' Healthy' if notion_healthy else ' Unhealthy'}")
        
        # Check Graph database
        graph_healthy = await sync_service.graph_client.health_check()
        print(f"Graph Database: {' Healthy' if graph_healthy else ' Unhealthy'}")
        
        overall_healthy = notion_healthy and graph_healthy
        print(f"\nOverall Status: {' All systems healthy' if overall_healthy else ' Some systems unhealthy'}")
        
        if not overall_healthy:
            sys.exit(1)
            
    except Exception as e:
        logger.exception(f"Health check failed: {e}")
        print(" Health check failed")
        sys.exit(1)
    finally:
        await sync_service.stop()


async def test_sync_components():
    """Test individual sync components."""
    logger.info("Testing sync components...")
    
    sync_service = SyncService()
    
    try:
        await sync_service.initialize()
        
        print("Testing components...")
        
        # Test scanner
        print("1. Testing Notion scanner...")
        try:
            # Scan for recent changes (last 1 day)
            last_day = datetime.now() - timedelta(days=1)
            pages = await sync_service.scanner.scan_for_changes(last_day)
            print(f"    Scanner found {len(pages)} recent pages")
        except Exception as e:
            print(f"    Scanner test failed: {e}")
        
        # Test graph operations
        print("2. Testing graph operations...")
        try:
            stats = await sync_service.graph_client.get_graph_stats()
            print(f"    Graph stats retrieved: {stats.total_pages} pages")
        except Exception as e:
            print(f"    Graph test failed: {e}")
        
        # Test updater (dry run)
        print("3. Testing graph updater...")
        try:
            # This is a minimal test - in a real scenario you'd want more comprehensive testing
            validation = await sync_service.updater.validate_graph_integrity()
            is_valid = validation.get('is_valid', False)
            print(f"   {'' if is_valid else ''} Graph integrity: {validation}")
        except Exception as e:
            print(f"    Updater test failed: {e}")
        
        print("\nComponent testing completed")
        
    except Exception as e:
        logger.exception(f"Component testing failed: {e}")
        sys.exit(1)
    finally:
        await sync_service.stop()


def main():
    """Main entry point."""
    setup_logging()
    
    parser = argparse.ArgumentParser(description="Manual sync script")
    parser.add_argument("--full", action="store_true", help="Perform full sync")
    parser.add_argument("--pages", nargs="+", help="Sync specific page IDs")
    parser.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("--health", action="store_true", help="Perform health check")
    parser.add_argument("--test", action="store_true", help="Test sync components")
    
    args = parser.parse_args()
    
    try:
        if args.stats:
            asyncio.run(sync_stats())
        elif args.health:
            asyncio.run(health_check())
        elif args.test:
            asyncio.run(test_sync_components())
        else:
            asyncio.run(run_manual_sync(
                full_sync=args.full,
                page_ids=args.pages
            ))
            
    except KeyboardInterrupt:
        logger.info("Manual sync cancelled by user")
        sys.exit(130)


if __name__ == "__main__":
    main()