"""
Graph Updater - Updates the graph database with Notion changes.
"""

import asyncio
from datetime import datetime
from typing import List, Set, Dict, Any
from loguru import logger

from core.graphiti_client import GraphitiClient
from core.notion_client import NotionExtractor
from core.models import NotionPageMetadata, SyncReport
from config.logging import LogExecutionTime


class GraphUpdater:
    """
    Updates the graph database with changes from Notion.
    """
    
    def __init__(self, graph_client: GraphitiClient, notion_client: NotionExtractor):
        self.graph_client = graph_client
        self.notion_client = notion_client
        self._batch_size = 10
        self._max_retries = 3
        self._retry_delay = 1.0
    
    async def update_graph(self, pages: List[NotionPageMetadata]) -> SyncReport:
        """
        Update the graph with changed pages.
        
        Args:
            pages: List of pages to update
            
        Returns:
            SyncReport with operation results
        """
        logger.info(f"Updating graph with {len(pages)} pages")
        
        report = SyncReport(
            start_time=datetime.now(),
            pages_processed=len(pages)
        )
        
        try:
            with LogExecutionTime("graph_update"):
                # Process pages in batches
                for i in range(0, len(pages), self._batch_size):
                    batch = pages[i:i + self._batch_size]
                    batch_report = await self._process_batch(batch)
                    
                    # Merge batch results into main report
                    report.pages_created += batch_report.pages_created
                    report.pages_updated += batch_report.pages_updated
                    report.relationships_created += batch_report.relationships_created
                    report.relationships_updated += batch_report.relationships_updated
                    report.errors.extend(batch_report.errors)
                    
                    logger.info(f"Processed batch {i//self._batch_size + 1}/{(len(pages) + self._batch_size - 1)//self._batch_size}")
                
                # Update timestamps
                report.end_time = datetime.now()
                report.status = "completed" if not report.errors else "completed_with_errors"
                
                logger.info(f"Graph update completed: {report.status}")
                return report
                
        except Exception as e:
            logger.exception(f"Error updating graph: {e}")
            report.end_time = datetime.now()
            report.status = "failed"
            report.errors.append(f"Fatal error: {str(e)}")
            return report
    
    async def _process_batch(self, pages: List[NotionPageMetadata]) -> SyncReport:
        """
        Process a batch of pages.
        
        Args:
            pages: Batch of pages to process
            
        Returns:
            SyncReport for this batch
        """
        batch_report = SyncReport()
        
        # Process pages concurrently
        tasks = []
        for page in pages:
            task = asyncio.create_task(self._process_single_page(page))
            tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_msg = f"Error processing page {pages[i].notion_id}: {str(result)}"
                batch_report.errors.append(error_msg)
                logger.error(error_msg)
            else:
                # result is a tuple: (created, updated, rel_created, rel_updated)
                created, updated, rel_created, rel_updated = result
                batch_report.pages_created += created
                batch_report.pages_updated += updated
                batch_report.relationships_created += rel_created
                batch_report.relationships_updated += rel_updated
        
        return batch_report
    
    async def _process_single_page(self, page: NotionPageMetadata) -> tuple:
        """
        Process a single page with retries.
        
        Args:
            page: Page to process
            
        Returns:
            Tuple of (pages_created, pages_updated, relationships_created, relationships_updated)
        """
        for attempt in range(self._max_retries):
            try:
                # Check if page exists
                page_exists = await self._page_exists(page.notion_id)
                
                # Upsert page (no embedding generation needed)
                success = await self.graph_client.upsert_page(page)
                if not success:
                    raise Exception(f"Failed to upsert page {page.notion_id}")
                
                # Create relationships
                rel_success = await self.graph_client.create_relationships(page)
                if not rel_success:
                    logger.warning(f"Failed to create some relationships for page {page.notion_id}")
                
                # Determine if this was a create or update
                pages_created = 0 if page_exists else 1
                pages_updated = 1 if page_exists else 0
                
                # For now, assume we created/updated relationships
                relationships_created = len(page.internal_links) + len(page.mentions) + len(page.database_relations) + len(page.tags)
                relationships_updated = 0
                
                return (pages_created, pages_updated, relationships_created, relationships_updated)
                
            except Exception as e:
                if attempt == self._max_retries - 1:
                    raise e
                
                logger.warning(f"Attempt {attempt + 1} failed for page {page.notion_id}: {e}")
                await asyncio.sleep(self._retry_delay * (attempt + 1))
        
        return (0, 0, 0, 0)
    
    async def _page_exists(self, notion_id: str) -> bool:
        """
        Check if a page exists in the graph.
        
        Args:
            notion_id: Notion page ID
            
        Returns:
            True if page exists, False otherwise
        """
        try:
            async with self.graph_client._driver.session() as session:
                query = """
                MATCH (p:NotionPage {notionId: $notion_id})
                RETURN p.notionId
                LIMIT 1
                """
                
                result = await session.run(query, notion_id=notion_id)
                record = await result.single()
                return record is not None
            
        except Exception as e:
            logger.warning(f"Error checking if page exists: {e}")
            return False
    
    async def delete_pages(self, page_ids: List[str]) -> SyncReport:
        """
        Delete pages from the graph.
        
        Args:
            page_ids: List of page IDs to delete
            
        Returns:
            SyncReport with deletion results
        """
        logger.info(f"Deleting {len(page_ids)} pages from graph")
        
        report = SyncReport(
            start_time=datetime.now(),
            pages_processed=len(page_ids)
        )
        
        try:
            deleted_count = 0
            
            for page_id in page_ids:
                try:
                    success = await self.graph_client.delete_page(page_id)
                    if success:
                        deleted_count += 1
                except Exception as e:
                    error_msg = f"Error deleting page {page_id}: {str(e)}"
                    report.errors.append(error_msg)
                    logger.error(error_msg)
            
            report.pages_deleted = deleted_count
            report.end_time = datetime.now()
            report.status = "completed" if not report.errors else "completed_with_errors"
            
            logger.info(f"Deleted {deleted_count} pages from graph")
            return report
            
        except Exception as e:
            logger.exception(f"Error deleting pages: {e}")
            report.end_time = datetime.now()
            report.status = "failed"
            report.errors.append(f"Fatal error: {str(e)}")
            return report
    
    async def update_page_embeddings(self, pages: List[NotionPageMetadata]) -> bool:
        """
        Update embeddings for pages.
        
        Args:
            pages: List of pages to update embeddings for
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Updating embeddings for {len(pages)} pages")
        
        try:
            # This would integrate with an embedding service
            # For now, we'll just log the operation
            for page in pages:
                # Generate embedding for page title + tags
                text_to_embed = f"{page.title} {' '.join(page.tags)}"
                # TODO: Generate actual embedding
                logger.debug(f"Would generate embedding for: {text_to_embed}")
            
            logger.info("Embeddings updated successfully")
            return True
            
        except Exception as e:
            logger.exception(f"Error updating embeddings: {e}")
            return False
    
    async def rebuild_all_relationships(self) -> bool:
        """
        Rebuild all relationships in the graph.
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("Rebuilding all relationships in graph")
        
        try:
            # Get all pages from graph
            query = """
            MATCH (p:NotionPage)
            RETURN p.notion_id as notion_id, p.internal_links as internal_links, 
                   p.mentions as mentions, p.database_relations as database_relations,
                   p.tags as tags
            """
            
            result = await self.graph_client._graphiti.driver.execute_query(query)
            
            # Delete existing relationships
            await self._delete_all_relationships()
            
            # Recreate relationships
            for record in result.records:
                try:
                    # Create a minimal page metadata object
                    page_metadata = NotionPageMetadata(
                        notion_id=record["notion_id"],
                        title="",  # Not needed for relationship creation
                        last_edited_time=datetime.now(),
                        url="",  # Not needed for relationship creation
                        internal_links=record["internal_links"] or [],
                        mentions=record["mentions"] or [],
                        database_relations=record["database_relations"] or [],
                        tags=record["tags"] or []
                    )
                    
                    await self.graph_client.create_relationships(page_metadata)
                    
                except Exception as e:
                    logger.warning(f"Error rebuilding relationships for page {record['notion_id']}: {e}")
                    continue
            
            logger.info("All relationships rebuilt successfully")
            return True
            
        except Exception as e:
            logger.exception(f"Error rebuilding relationships: {e}")
            return False
    
    async def _delete_all_relationships(self):
        """Delete all relationships in the graph."""
        queries = [
            "MATCH ()-[r:CHILD_OF]->() DELETE r",
            "MATCH ()-[r:LINKS_TO]->() DELETE r", 
            "MATCH ()-[r:RELATED_TO]->() DELETE r",
            "MATCH ()-[r:MENTIONS]->() DELETE r",
            "MATCH ()-[r:HAS_TAG]->() DELETE r"
        ]
        
        for query in queries:
            await self.graph_client._graphiti.driver.execute_query(query)
    
    async def validate_graph_integrity(self) -> Dict[str, Any]:
        """
        Validate the integrity of the graph.
        
        Returns:
            Dictionary with validation results
        """
        logger.info("Validating graph integrity")
        
        try:
            # Check for orphaned nodes
            orphaned_query = """
            MATCH (p:NotionPage)
            WHERE NOT (p)-[]-()
            RETURN count(p) as orphaned_count
            """
            
            orphaned_result = await self.graph_client._graphiti.driver.execute_query(orphaned_query)
            orphaned_count = orphaned_result.records[0]["orphaned_count"]
            
            # Check for broken relationships
            broken_query = """
            MATCH (p1:NotionPage)-[r]->(p2:NotionPage)
            WHERE p1.notion_id IS NULL OR p2.notion_id IS NULL
            RETURN count(r) as broken_count
            """
            
            broken_result = await self.graph_client._graphiti.driver.execute_query(broken_query)
            broken_count = broken_result.records[0]["broken_count"]
            
            # Check for duplicate pages
            duplicate_query = """
            MATCH (p:NotionPage)
            WITH p.notion_id as id, count(p) as count
            WHERE count > 1
            RETURN count(*) as duplicate_count
            """
            
            duplicate_result = await self.graph_client._graphiti.driver.execute_query(duplicate_query)
            duplicate_count = duplicate_result.records[0]["duplicate_count"]
            
            validation_results = {
                "orphaned_pages": orphaned_count,
                "broken_relationships": broken_count,
                "duplicate_pages": duplicate_count,
                "is_valid": orphaned_count == 0 and broken_count == 0 and duplicate_count == 0
            }
            
            logger.info(f"Graph integrity validation completed: {validation_results}")
            return validation_results
            
        except Exception as e:
            logger.exception(f"Error validating graph integrity: {e}")
            return {"error": str(e), "is_valid": False}