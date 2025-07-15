"""
Notion Scanner - Scans Notion for changes and new content.
"""

import asyncio
import re
from datetime import datetime
from typing import List, Optional, Set, Dict, Any
from loguru import logger

from core.notion_client import NotionExtractor
from core.models import NotionPageMetadata, extract_title_from_page
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
                # print(pages)
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
    
    
    
    
    
    
    def reset_scan_state(self):
        """Reset the scanner state for a fresh scan."""
        self._processed_pages.clear()
        self._last_scan_time = None
        logger.info("Scanner state reset")
    
    async def extract_relationships_from_content(self, page_id: str) -> tuple[List[str], List[str]]:
        """
        Extract internal links and mentions from page content.
        处理Notion的结构化mention对象和文本链接。
        
        Args:
            page_id: Notion page ID
            
        Returns:
            Tuple of (page_ids_from_mentions, text_links_and_mentions)
        """
        try:
            # 使用extractor来获取blocks
            blocks = await self.notion_client.client.blocks.children.list(
                block_id=page_id,
                page_size=20
            )
            
            page_mentions = []  # 结构化mention中的页面ID
            text_links = []     # 文本中的[[...]]链接和@提及
            
            for block in blocks["results"]:
                # 处理结构化mention
                block_mentions = self._extract_structured_mentions(block)
                page_mentions.extend(block_mentions)
                
                # 处理文本链接
                text = self._extract_text_from_block(block)
                if text:
                    # Extract [[internal links]]
                    text_links.extend(re.findall(r'\[\[([^\]]+)\]\]', text))
                    # Extract @mentions
                    text_links.extend(re.findall(r'@(\w+)', text))
            
            return list(set(page_mentions)), list(set(text_links))
            
        except Exception as e:
            logger.warning(f"Could not extract relationships from page {page_id}: {e}")
            return [], []
    
    def _extract_structured_mentions(self, block: Dict[str, Any]) -> List[str]:
        """
        从block中提取结构化的页面mention
        
        Args:
            block: Notion block对象
            
        Returns:
            提取到的页面ID列表
        """
        page_ids = []
        block_type = block.get("type", "")
        
        # 处理包含rich_text的block类型
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item", "quote", "callout"]:
            rich_text = block.get(block_type, {}).get("rich_text", [])
            
            for text_obj in rich_text:
                # 检查是否为mention类型
                if text_obj.get("type") == "mention":
                    mention = text_obj.get("mention", {})
                    
                    # 处理页面mention
                    if mention.get("type") == "page":
                        page_id = mention.get("page", {}).get("id")
                        if page_id:
                            # 去掉连字符，标准化为32位ID
                            clean_id = page_id.replace("-", "")
                            page_ids.append(clean_id)
        
        return page_ids
    
    def _extract_text_from_block(self, block: Dict[str, Any]) -> str:
        """
        Extract plain text from a Notion block.
        
        Args:
            block: Notion block object
            
        Returns:
            Plain text string
        """
        block_type = block.get("type", "")
        text_content = ""
        
        # Handle different block types
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item"]:
            rich_text = block.get(block_type, {}).get("rich_text", [])
            text_content = "".join([item.get("plain_text", "") for item in rich_text])
        elif block_type == "quote":
            rich_text = block.get("quote", {}).get("rich_text", [])
            text_content = "".join([item.get("plain_text", "") for item in rich_text])
        elif block_type == "callout":
            rich_text = block.get("callout", {}).get("rich_text", [])
            text_content = "".join([item.get("plain_text", "") for item in rich_text])
        elif block_type == "code":
            rich_text = block.get("code", {}).get("rich_text", [])
            text_content = "".join([item.get("plain_text", "") for item in rich_text])
        
        return text_content
    
    async def find_page_id_by_title(self, title: str) -> Optional[str]:
        """
        通过标题查找页面ID
        
        Args:
            title: 页面标题
            
        Returns:
            页面ID或None
        """
        try:
            # 搜索标题匹配的页面
            await self.notion_client._rate_limit_wait()
            results = await self.notion_client.client.search(
                query=title,
                filter={
                    "value": "page",
                    "property": "object"
                },
                page_size=5
            )
            
            # 查找最匹配的页面
            for result in results.get("results", []):
                page_title = extract_title_from_page(result)
                # 精确匹配或包含匹配
                if page_title and (page_title.lower() == title.lower() or title.lower() in page_title.lower()):
                    return result["id"].replace("-", "")
            
            return None
            
        except Exception as e:
            logger.debug(f"通过标题查找页面失败 '{title}': {e}")
            return None
    
