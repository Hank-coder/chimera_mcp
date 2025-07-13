"""
Notion Scanner - Scans Notion for changes and new content.
"""

import asyncio
from datetime import datetime
from typing import List, Optional, Set
from loguru import logger

from core.notion_client import NotionExtractor
from core.models import NotionPageMetadata
from config.logging import LogExecutionTime


class NotionScanner:
    """
    Scans Notion for pages and detects changes.
    """
    
    def __init__(self, notion_client: NotionExtractor):
        self.notion_client = notion_client
        self._last_scan_time = None
        self._processed_pages = set()
    
    async def scan_for_changes(self, last_sync_time: Optional[datetime] = None) -> List[NotionPageMetadata]:
        """
        Scan Notion for pages that have changed since the last sync.
        
        Args:
            last_sync_time: Time of last sync (None for full scan)
            
        Returns:
            List of changed pages
        """
        logger.info(f"Scanning Notion for changes since {last_sync_time}")
        
        try:
            with LogExecutionTime("notion_scan"):
                # Get all pages metadata
                pages = await self.notion_client.get_all_pages_metadata(last_sync_time)
                
                # Filter out pages we've already processed in this session
                new_pages = []
                for page in pages:
                    if page.notion_id not in self._processed_pages:
                        new_pages.append(page)
                        self._processed_pages.add(page.notion_id)
                
                logger.info(f"Found {len(new_pages)} new/changed pages")
                return new_pages
                
        except Exception as e:
            logger.exception(f"Error scanning Notion: {e}")
            return []
    
    async def scan_full_workspace(self) -> List[NotionPageMetadata]:
        """
        Perform a full scan of the entire Notion workspace.
        
        Returns:
            List of all pages in the workspace
        """
        logger.info("Performing full workspace scan")
        
        try:
            with LogExecutionTime("full_workspace_scan"):
                # Get all pages without time filter
                pages = await self.notion_client.get_all_pages_metadata()
                
                # Also get database pages
                databases = await self.notion_client.get_databases()
                
                # Process database pages
                for db in databases:
                    try:
                        db_pages = await self.notion_client.get_database_pages(db["id"])
                        for db_page in db_pages:
                            # Convert to metadata
                            metadata = await self.notion_client._extract_page_metadata(db_page)
                            if metadata:
                                pages.append(metadata)
                    except Exception as e:
                        logger.warning(f"Error scanning database {db['id']}: {e}")
                        continue
                
                logger.info(f"Full scan found {len(pages)} pages")
                return pages
                
        except Exception as e:
            logger.exception(f"Error in full workspace scan: {e}")
            return []
    
    async def scan_specific_pages(self, page_ids: List[str]) -> List[NotionPageMetadata]:
        """
        Scan specific pages by their IDs.
        
        Args:
            page_ids: List of Notion page IDs to scan
            
        Returns:
            List of page metadata
        """
        logger.info(f"Scanning {len(page_ids)} specific pages")
        
        pages = []
        for page_id in page_ids:
            try:
                # Get basic page info
                page_info = await self.notion_client.get_page_basic_info(page_id)
                if page_info:
                    # Convert to full metadata
                    metadata = await self.notion_client._extract_page_metadata(page_info)
                    if metadata:
                        pages.append(metadata)
            except Exception as e:
                logger.warning(f"Error scanning page {page_id}: {e}")
                continue
        
        logger.info(f"Successfully scanned {len(pages)} specific pages")
        return pages
    
    async def detect_deleted_pages(self, known_page_ids: Set[str]) -> List[str]:
        """
        Detect pages that have been deleted from Notion.
        
        Args:
            known_page_ids: Set of page IDs we know about
            
        Returns:
            List of page IDs that appear to be deleted
        """
        logger.info(f"Checking for deleted pages among {len(known_page_ids)} known pages")
        
        deleted_pages = []
        
        # Sample check - check a subset of known pages
        sample_size = min(100, len(known_page_ids))
        sample_pages = list(known_page_ids)[:sample_size]
        
        for page_id in sample_pages:
            try:
                page_info = await self.notion_client.get_page_basic_info(page_id)
                if page_info is None:
                    # Page might be deleted or access revoked
                    deleted_pages.append(page_id)
                    
            except Exception as e:
                # If we can't access the page, it might be deleted
                logger.debug(f"Could not access page {page_id}: {e}")
                deleted_pages.append(page_id)
        
        if deleted_pages:
            logger.info(f"Found {len(deleted_pages)} potentially deleted pages")
        
        return deleted_pages
    
    async def validate_page_access(self, page_id: str) -> bool:
        """
        Validate that we can access a specific page.
        
        Args:
            page_id: Notion page ID
            
        Returns:
            True if accessible, False otherwise
        """
        try:
            page_info = await self.notion_client.get_page_basic_info(page_id)
            return page_info is not None
        except Exception:
            return False
    
    async def get_scan_statistics(self) -> dict:
        """
        Get statistics about the scanning process.
        
        Returns:
            Dictionary with scan statistics
        """
        return {
            "last_scan_time": self._last_scan_time,
            "processed_pages_count": len(self._processed_pages),
            "processed_pages": list(self._processed_pages)
        }
    
    def reset_scan_state(self):
        """Reset the scanner state for a fresh scan."""
        self._processed_pages.clear()
        self._last_scan_time = None
        logger.info("Scanner state reset")
    
    async def incremental_scan(self, batch_size: int = 50) -> List[NotionPageMetadata]:
        """
        Perform an incremental scan with batching.
        
        Args:
            batch_size: Number of pages to process per batch
            
        Returns:
            List of changed pages
        """
        logger.info(f"Starting incremental scan with batch size {batch_size}")
        
        all_pages = []
        
        try:
            # Get all pages
            pages = await self.notion_client.get_all_pages_metadata()
            
            # Process in batches
            for i in range(0, len(pages), batch_size):
                batch = pages[i:i + batch_size]
                
                # Process batch
                for page in batch:
                    if page.notion_id not in self._processed_pages:
                        all_pages.append(page)
                        self._processed_pages.add(page.notion_id)
                
                logger.info(f"Processed batch {i//batch_size + 1}, "
                           f"found {len(all_pages)} pages so far")
                
                # Small delay between batches
                await asyncio.sleep(0.1)
            
            logger.info(f"Incremental scan completed, found {len(all_pages)} pages")
            return all_pages
            
        except Exception as e:
            logger.exception(f"Error in incremental scan: {e}")
            return all_pages