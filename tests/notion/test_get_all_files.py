"""
Test for retrieving all files from Notion workspace.
Tests the core functionality of the NotionExtractor class.
"""
import asyncio
import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from core.notion_client import NotionExtractor
from core.models import NotionPageMetadata, NodeType
from config.settings import get_settings


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = Mock()
    settings.notion_token = "test_token"
    settings.notion_rate_limit_per_second = 3
    return settings


@pytest.fixture
def notion_extractor(mock_settings):
    """Create NotionExtractor instance with mocked settings."""
    return NotionExtractor(
        api_key=mock_settings.notion_token,
        rate_limit_per_second=mock_settings.notion_rate_limit_per_second
    )


class TestNotionGetAllFiles:
    """Test cases for retrieving all files from Notion."""

    @pytest.mark.asyncio
    async def test_get_all_pages_metadata_success(self, notion_extractor):
        """Test successful retrieval of all pages metadata."""
        # Mock page data
        mock_page_data = {
            "id": "test-page-id-1",
            "url": "https://www.notion.so/test-page-id-1",
            "last_edited_time": "2024-01-01T00:00:00.000Z",
            "properties": {
                "title": {
                    "type": "title",
                    "title": [{"plain_text": "Test Page"}]
                },
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "test"}]
                }
            },
            "parent": {
                "type": "workspace",
                "workspace": True
            }
        }

        # Mock the async_collect_paginated_api function
        with patch('core.notion_client.async_collect_paginated_api') as mock_collect:
            mock_collect.return_value = [mock_page_data]
            
            # Mock the internal methods
            with patch.object(notion_extractor, '_extract_page_metadata') as mock_extract:
                mock_metadata = NotionPageMetadata(
                    notion_id="test-page-id-1",
                    title="Test Page",
                    type=NodeType.PAGE,
                    tags=["test"],
                    last_edited_time=datetime(2024, 1, 1),
                    url="https://www.notion.so/test-page-id-1",
                    parent_id=None,
                    internal_links=[],
                    mentions=[],
                    database_relations=[]
                )
                mock_extract.return_value = mock_metadata

                # Execute the test
                result = await notion_extractor.get_all_pages_metadata()

                # Assertions
                assert len(result) == 1
                assert result[0].notion_id == "test-page-id-1"
                assert result[0].title == "Test Page"
                assert result[0].type == NodeType.PAGE
                assert "test" in result[0].tags

    @pytest.mark.asyncio
    async def test_get_all_pages_metadata_with_incremental_sync(self, notion_extractor):
        """Test retrieval with incremental sync (after specific timestamp)."""
        last_sync_time = datetime(2024, 1, 1)
        
        # Mock page data - one before and one after the sync time
        mock_page_old = {
            "id": "old-page-id",
            "url": "https://www.notion.so/old-page-id",
            "last_edited_time": "2023-12-31T23:59:59.000Z",
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": "Old Page"}]}
            },
            "parent": {"type": "workspace", "workspace": True}
        }
        
        mock_page_new = {
            "id": "new-page-id",
            "url": "https://www.notion.so/new-page-id",
            "last_edited_time": "2024-01-02T00:00:00.000Z",
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": "New Page"}]}
            },
            "parent": {"type": "workspace", "workspace": True}
        }
        
        with patch('core.notion_client.async_collect_paginated_api') as mock_collect:
            mock_collect.return_value = [mock_page_old, mock_page_new]
            
            # Mock the internal extraction method
            with patch.object(notion_extractor, '_extract_page_metadata') as mock_extract:
                def mock_extract_side_effect(page):
                    if page["id"] == "new-page-id":
                        return NotionPageMetadata(
                            notion_id="new-page-id",
                            title="New Page",
                            type=NodeType.PAGE,
                            tags=[],
                            last_edited_time=datetime(2024, 1, 2),
                            url="https://www.notion.so/new-page-id",
                            parent_id=None,
                            internal_links=[],
                            mentions=[],
                            database_relations=[]
                        )
                    return None  # Old page is filtered out
                
                mock_extract.side_effect = mock_extract_side_effect
                
                # Execute the test
                result = await notion_extractor.get_all_pages_metadata(last_sync_time)
                
                # Should only return the new page (after the sync time)
                assert len(result) == 1
                assert result[0].notion_id == "new-page-id"
                assert result[0].title == "New Page"

    @pytest.mark.asyncio
    async def test_get_all_pages_metadata_error_handling(self, notion_extractor):
        """Test error handling when page extraction fails."""
        mock_page_data = {
            "id": "test-page-id-1",
            "url": "https://www.notion.so/test-page-id-1",
            "last_edited_time": "2024-01-01T00:00:00.000Z",
            "properties": {}
        }

        with patch('core.notion_client.async_collect_paginated_api') as mock_collect:
            mock_collect.return_value = [mock_page_data]
            
            # Mock extraction to raise an exception
            with patch.object(notion_extractor, '_extract_page_metadata') as mock_extract:
                mock_extract.side_effect = Exception("Extraction failed")

                # Execute the test
                result = await notion_extractor.get_all_pages_metadata()

                # Should return empty list when extraction fails
                assert result == []

    @pytest.mark.asyncio
    async def test_get_databases(self, notion_extractor):
        """Test retrieval of all databases."""
        mock_database_data = {
            "id": "test-database-id-1",
            "title": [{"plain_text": "Test Database"}],
            "properties": {}
        }

        with patch('core.notion_client.async_collect_paginated_api') as mock_collect:
            mock_collect.return_value = [mock_database_data]
            
            # Execute the test
            result = await notion_extractor.get_databases()

            # Assertions
            assert len(result) == 1
            assert result[0]["id"] == "test-database-id-1"

    @pytest.mark.asyncio
    async def test_get_database_pages(self, notion_extractor):
        """Test retrieval of pages from a specific database."""
        database_id = "test-database-id"
        mock_page_data = {
            "id": "test-page-id-1",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "Database Page"}]
                }
            }
        }

        with patch('core.notion_client.async_collect_paginated_api') as mock_collect:
            mock_collect.return_value = [mock_page_data]
            
            # Execute the test
            result = await notion_extractor.get_database_pages(database_id)

            # Assertions
            assert len(result) == 1
            assert result[0]["id"] == "test-page-id-1"

    @pytest.mark.asyncio
    async def test_health_check_success(self, notion_extractor):
        """Test successful health check."""
        with patch.object(notion_extractor.client, 'search') as mock_search:
            # Mock the async search method to return a coroutine
            async def mock_search_async(*args, **kwargs):
                return {"results": []}
            
            mock_search.side_effect = mock_search_async
            
            # Execute the test
            result = await notion_extractor.health_check()

            # Assertions
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, notion_extractor):
        """Test failed health check."""
        with patch.object(notion_extractor.client, 'search') as mock_search:
            mock_search.side_effect = Exception("API Error")
            
            # Execute the test
            result = await notion_extractor.health_check()

            # Assertions
            assert result is False

    @pytest.mark.asyncio
    async def test_rate_limiting(self, notion_extractor):
        """Test that rate limiting is applied correctly."""
        # Mock the event loop time
        with patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value.time.return_value = 1.0
            
            # First call should not wait
            await notion_extractor._rate_limit_wait()
            
            # Second call should wait
            mock_loop.return_value.time.return_value = 1.1
            with patch('asyncio.sleep') as mock_sleep:
                await notion_extractor._rate_limit_wait()
                # Should sleep for the remaining time
                mock_sleep.assert_called_once()


class TestNotionGetAllFilesIntegration:
    """Integration tests with real Notion API (requires valid token)."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_notion_api_get_all_files(self):
        """
        Integration test with real Notion API.
        Skipped by default - run with: pytest -m integration
        """
        settings = get_settings()
        
        # Skip if no real token provided
        if not settings.notion_token or settings.notion_token.startswith("test_"):
            pytest.skip("Real Notion token required for integration test")
        
        extractor = NotionExtractor(settings.notion_token)
        
        # Test health check first
        health_ok = await extractor.health_check()
        assert health_ok, "Notion API health check failed"
        
        # Get all pages metadata
        pages = await extractor.get_all_pages_metadata()
        
        # Basic assertions
        assert isinstance(pages, list)
        print(f"Found {len(pages)} pages in Notion workspace")
        
        # If there are pages, verify structure
        if pages:
            first_page = pages[0]
            assert hasattr(first_page, 'notion_id')
            assert hasattr(first_page, 'title')
            assert hasattr(first_page, 'type')
            assert hasattr(first_page, 'last_edited_time')
            assert hasattr(first_page, 'url')
            print(f"First page: {first_page.title} ({first_page.notion_id})")
        
        # Test getting databases
        databases = await extractor.get_databases()
        assert isinstance(databases, list)
        print(f"Found {len(databases)} databases in Notion workspace")
        
        # Test getting content from a page if available
        if pages:
            page_id = pages[0].notion_id
            content = await extractor.get_page_content(page_id)
            assert isinstance(content, str) or content is None
            print(f"Content length for first page: {len(content) if content else 0}")


if __name__ == "__main__":
    """Run the tests directly."""
    # Run unit tests
    pytest.main([__file__, "-v"])
    
    # Run integration tests (uncomment if you want to test with real API)
    # pytest.main([__file__, "-v", "-m", "integration"])