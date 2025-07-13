import asyncio
import re
from typing import List, Dict, Optional, Any, Set
from datetime import datetime
from notion_client import AsyncClient
from notion_client.helpers import async_collect_paginated_api
from loguru import logger

from .models import (
    NotionPageMetadata, 
    NodeType, 
    create_notion_page_from_api,
    extract_title_from_page,
    extract_tags_from_page,
    extract_parent_id_from_page
)


class NotionExtractor:
    """
    Enhanced Notion API client for extracting structured data.
    Based on the tutorial but expanded for the full system requirements.
    """
    
    def __init__(self, api_key: str, rate_limit_per_second: int = 3):
        self.client = AsyncClient(auth=api_key)
        self.rate_limit = rate_limit_per_second
        self._last_request_time = 0
        
    async def _rate_limit_wait(self):
        """Simple rate limiting to respect Notion API limits."""
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - self._last_request_time
        min_interval = 1.0 / self.rate_limit
        
        if time_since_last < min_interval:
            await asyncio.sleep(min_interval - time_since_last)
        
        self._last_request_time = asyncio.get_event_loop().time()
    
    async def get_all_pages_metadata(self, last_sync_time: Optional[datetime] = None) -> List[NotionPageMetadata]:
        """
        Get metadata for all pages, with optional incremental sync.
        
        Args:
            last_sync_time: Only get pages modified after this time
            
        Returns:
            List of NotionPageMetadata objects
        """
        logger.info("Starting to fetch all pages metadata")
        
        # Build search parameters
        search_params = {
            "filter": {"value": "page", "property": "object"},
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}]
        }
        
        await self._rate_limit_wait()
        pages = await async_collect_paginated_api(
            self.client.search,
            **search_params
        )
        
        # Apply incremental sync filter locally if needed
        if last_sync_time:
            # Make sure last_sync_time is timezone-aware
            if last_sync_time.tzinfo is None:
                from datetime import timezone
                last_sync_time = last_sync_time.replace(tzinfo=timezone.utc)
            
            pages = [
                page for page in pages
                if datetime.fromisoformat(page["last_edited_time"].replace("Z", "+00:00")) > last_sync_time
            ]
        
        logger.info(f"Found {len(pages)} pages to process")
        
        metadata_list = []
        for i, page in enumerate(pages):
            try:
                await self._rate_limit_wait()
                metadata = await self._extract_page_metadata(page)
                if metadata:
                    metadata_list.append(metadata)
                    
                if (i + 1) % 10 == 0:
                    logger.info(f"Processed {i + 1}/{len(pages)} pages")
                    
            except Exception as e:
                logger.error(f"Error processing page {page.get('id', 'unknown')}: {e}")
                continue
        
        logger.info(f"Successfully extracted metadata for {len(metadata_list)} pages")
        return metadata_list
    
    async def _extract_page_metadata(self, page: Dict[str, Any]) -> Optional[NotionPageMetadata]:
        """
        Extract comprehensive metadata from a Notion page.
        
        Args:
            page: Raw page data from Notion API
            
        Returns:
            NotionPageMetadata object or None if extraction fails
        """
        try:
            # Basic metadata from page object
            notion_id = page["id"]
            title = extract_title_from_page(page)
            tags = extract_tags_from_page(page)
            last_edited_time = datetime.fromisoformat(page["last_edited_time"].replace("Z", "+00:00"))
            url = page["url"]
            parent_id = extract_parent_id_from_page(page)
            
            # Extract relationships from page content
            internal_links, mentions = await self._extract_relationships_from_content(notion_id)
            
            # Extract database relations
            database_relations = self._extract_database_relations(page)
            
            # Calculate hierarchy level
            level = await self._calculate_page_level(parent_id) if parent_id else 0
            
            metadata = NotionPageMetadata(
                notion_id=notion_id,
                title=title,
                type=NodeType.PAGE,
                tags=tags,
                last_edited_time=last_edited_time,
                url=url,
                parent_id=parent_id,
                level=level,
                internal_links=internal_links,
                mentions=mentions,
                database_relations=database_relations
            )
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting metadata for page {page.get('id', 'unknown')}: {e}")
            return None
    
    async def _extract_relationships_from_content(self, page_id: str) -> tuple[List[str], List[str]]:
        """
        Extract internal links and mentions from page content.
        Only reads first 10 blocks to avoid API limits.
        
        Args:
            page_id: Notion page ID
            
        Returns:
            Tuple of (internal_links, mentions)
        """
        try:
            await self._rate_limit_wait()
            blocks = await self.client.blocks.children.list(
                block_id=page_id,
                page_size=10
            )
            
            internal_links = []
            mentions = []
            
            for block in blocks["results"]:
                text = self._extract_text_from_block(block)
                if text:
                    # Extract [[internal links]]
                    internal_links.extend(re.findall(r'\[\[([^\]]+)\]\]', text))
                    # Extract @mentions
                    mentions.extend(re.findall(r'@(\w+)', text))
            
            return list(set(internal_links)), list(set(mentions))
            
        except Exception as e:
            logger.warning(f"Could not extract relationships from page {page_id}: {e}")
            return [], []
    
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
    
    def _extract_database_relations(self, page: Dict[str, Any]) -> List[str]:
        """
        Extract database relation property IDs from page properties.
        
        Args:
            page: Notion page object
            
        Returns:
            List of relation property IDs
        """
        relations = []
        properties = page.get("properties", {})
        
        for prop_data in properties.values():
            if prop_data.get("type") == "relation":
                relation_items = prop_data.get("relation", [])
                for item in relation_items:
                    if "id" in item:
                        relations.append(item["id"])
        
        return relations
    
    async def _calculate_page_level(self, parent_id: str, max_depth: int = 10) -> int:
        """
        Calculate the hierarchy level of a page by traversing up the parent chain.
        
        Args:
            parent_id: Parent page ID
            max_depth: Maximum depth to prevent infinite loops
            
        Returns:
            Hierarchy level (0=root, 1=child, 2=grandchild, etc.)
        """
        if not parent_id or max_depth <= 0:
            return 0
            
        try:
            await self._rate_limit_wait()
            parent_page = await self.client.pages.retrieve(page_id=parent_id)
            
            # Get parent's parent
            parent_parent_id = extract_parent_id_from_page(parent_page)
            
            if parent_parent_id:
                # Recursively calculate parent's level and add 1
                parent_level = await self._calculate_page_level(parent_parent_id, max_depth - 1)
                return parent_level + 1
            else:
                # Parent is root level, so current page is level 1
                return 1
                
        except Exception as e:
            logger.warning(f"Could not calculate level for parent {parent_id}: {e}")
            return 1  # Default to level 1 if can't determine
    
    async def get_page_content(self, page_id: str) -> Optional[str]:
        """
        Get full content of a specific page.
        
        Args:
            page_id: Notion page ID
            
        Returns:
            Page content as markdown string or None if failed
        """
        try:
            await self._rate_limit_wait()
            blocks = await async_collect_paginated_api(
                self.client.blocks.children.list,
                block_id=page_id
            )
            
            content_parts = []
            for block in blocks:
                text = self._extract_text_from_block(block)
                if text:
                    content_parts.append(text)
            
            return "\n\n".join(content_parts)
            
        except Exception as e:
            logger.error(f"Error getting content for page {page_id}: {e}")
            return None
    
    async def get_page_content_with_files(self, page_id: str) -> Optional[str]:
        """
        Get full content of a specific page including file content.
        
        Args:
            page_id: Notion page ID
            
        Returns:
            Page content with extracted file content as markdown string or None if failed
        """
        try:
            await self._rate_limit_wait()
            blocks = await async_collect_paginated_api(
                self.client.blocks.children.list,
                block_id=page_id
            )
            
            content_parts = []
            for block in blocks:
                # 处理文本内容
                text = self._extract_text_from_block(block)
                if text:
                    content_parts.append(text)
                
                # 处理文件块
                if block.get("type") == "file":
                    file_content = await self._extract_file_block_content(block)
                    if file_content:
                        content_parts.append(file_content)
            
            return "\n\n".join(content_parts)
            
        except Exception as e:
            logger.error(f"Error getting content with files for page {page_id}: {e}")
            return None
    
    async def _extract_file_block_content(self, block: Dict[str, Any]) -> Optional[str]:
        """
        Extract content from a file block.
        
        Args:
            block: Notion file block object
            
        Returns:
            Extracted file content or None if failed
        """
        try:
            file_info = block.get("file", {})
            
            # 获取文件URL
            file_url = None
            if "external" in file_info:
                file_url = file_info["external"]["url"]
            elif "file" in file_info:
                file_url = file_info["file"]["url"]
            
            if not file_url:
                return None
            
            # 获取文件名
            caption = ""
            if "caption" in file_info and file_info["caption"]:
                caption = "".join([item.get("plain_text", "") for item in file_info["caption"]])
            
            # 推断文件类型，正确处理AWS S3 URL
            import re
            import urllib.parse
            
            try:
                # 解析URL获取路径
                parsed_url = urllib.parse.urlparse(file_url)
                path = parsed_url.path
                
                # 提取文件名
                filename_match = re.search(r'/([^/]+)$', path)
                if filename_match:
                    filename = filename_match.group(1)
                    # URL解码
                    decoded_filename = urllib.parse.unquote(filename)
                    
                    # 提取扩展名
                    ext_match = re.search(r'\.([^.]+)$', decoded_filename)
                    if ext_match:
                        file_type = ext_match.group(1).lower()
                    else:
                        return f"[文件: {caption}] (无法从文件名提取扩展名)"
                else:
                    return f"[文件: {caption}] (无法从URL提取文件名)"
            except Exception as e:
                logger.warning(f"解析文件URL失败: {e}")
                return f"[文件: {caption}] (URL解析失败)"
            
            # 提取文件内容
            from core.file_extractor import file_extractor
            content, metadata = await file_extractor.extract_file_content(
                file_url, file_type, caption
            )
            
            return content
            
        except Exception as e:
            logger.error(f"Error extracting file block content: {e}")
            return None
    
    async def get_pages_content_batch(self, page_ids: List[str]) -> Dict[str, str]:
        """
        Get content for multiple pages with rate limiting.
        
        Args:
            page_ids: List of Notion page IDs
            
        Returns:
            Dictionary mapping page_id to content
        """
        results = {}
        
        for page_id in page_ids:
            content = await self.get_page_content(page_id)
            if content:
                results[page_id] = content
                
        return results
    
    async def get_page_basic_info(self, page_id: str) -> Optional[Dict[str, Any]]:
        """
        Get basic page information without content.
        
        Args:
            page_id: Notion page ID
            
        Returns:
            Basic page info dictionary or None if failed
        """
        try:
            await self._rate_limit_wait()
            page = await self.client.pages.retrieve(page_id=page_id)
            
            return {
                "id": page["id"],
                "title": extract_title_from_page(page),
                "url": page["url"],
                "last_edited_time": page["last_edited_time"],
                "tags": extract_tags_from_page(page)
            }
            
        except Exception as e:
            logger.error(f"Error getting basic info for page {page_id}: {e}")
            return None
    
    async def health_check(self) -> bool:
        """
        Check if the Notion API is accessible.
        
        Returns:
            True if API is accessible, False otherwise
        """
        try:
            await self._rate_limit_wait()
            # Try to search for any page to test connection
            # Use simple search without filter for health check
            response = await self.client.search(
                page_size=1
            )
            return True
            
        except Exception as e:
            logger.error(f"Notion API health check failed: {e}")
            return False
    
    async def get_databases(self) -> List[Dict[str, Any]]:
        """
        Get all databases accessible to the integration.
        
        Returns:
            List of database objects
        """
        try:
            await self._rate_limit_wait()
            databases = await async_collect_paginated_api(
                self.client.search,
                filter={"value": "database", "property": "object"}
            )
            
            return databases
            
        except Exception as e:
            logger.error(f"Error getting databases: {e}")
            return []
    
    async def get_database_pages(self, database_id: str) -> List[Dict[str, Any]]:
        """
        Get all pages from a specific database.
        
        Args:
            database_id: Database ID
            
        Returns:
            List of page objects from the database
        """
        try:
            await self._rate_limit_wait()
            pages = await async_collect_paginated_api(
                self.client.databases.query,
                database_id=database_id
            )
            
            return pages
            
        except Exception as e:
            logger.error(f"Error getting pages from database {database_id}: {e}")
            return []


class NotionClient:
    """
    简化的Notion客户端，专门为意图搜索系统提供标准接口
    """
    
    def __init__(self, api_key: str = None):
        from config.settings import settings
        self.api_key = api_key or settings.notion_token
        self.extractor = NotionExtractor(self.api_key)
    
    def _normalize_page_id(self, page_id: str) -> str:
        """
        规范化页面ID为UUID格式
        
        Args:
            page_id: 原始页面ID
            
        Returns:
            规范化的UUID格式页面ID
        """
        # 移除所有连字符
        clean_id = page_id.replace("-", "")
        
        # 如果长度不是32位，返回原ID（可能是非标准格式）
        if len(clean_id) != 32:
            logger.warning(f"页面ID长度异常: {len(clean_id)} (期望32位) - {page_id}")
            return page_id
        
        # 转换为UUID格式: 8-4-4-4-12
        uuid_format = f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:32]}"
        return uuid_format
    
    async def get_page_content(self, page_id: str, include_files: bool = False, max_length: int = 0) -> str:
        """
        获取页面内容
        
        Args:
            page_id: 页面ID
            include_files: 是否提取文档文件内容
            max_length: 内容最大长度限制，0表示不限制
        """
        try:
            # 规范化页面ID
            normalized_id = self._normalize_page_id(page_id)
            
            if include_files:
                content = await self.extractor.get_page_content_with_files(normalized_id)
            else:
                content = await self.extractor.get_page_content(normalized_id)
                
            if content and content.strip():
                content = content.strip()
                
                # 应用长度限制
                if max_length > 0 and len(content) > max_length:
                    content = self._truncate_page_content(content, max_length)
                
                return content
            else:
                # 页面存在但内容为空
                page_info = await self.extractor.get_page_basic_info(page_id)
                page_title = page_info.get('title', 'Unknown') if page_info else 'Unknown'
                return f"页面 '{page_title}' 当前没有内容，这可能是一个空白页面或仅包含标题的页面。"
        except Exception as e:
            return f"无法获取页面内容: {str(e)}"
    
    def _truncate_page_content(self, content: str, max_length: int) -> str:
        """
        智能截断页面内容
        
        Args:
            content: 原始内容
            max_length: 最大长度
            
        Returns:
            截断后的内容
        """
        if len(content) <= max_length:
            return content
        
        # 按段落分割内容
        paragraphs = content.split('\n\n')
        
        # 保留开头的重要段落
        truncated_parts = []
        current_length = 0
        preserve_length = int(max_length * 0.85)  # 预留15%空间给提示信息
        
        for paragraph in paragraphs:
            para_length = len(paragraph) + 2  # +2 for \n\n
            
            if current_length + para_length <= preserve_length:
                truncated_parts.append(paragraph)
                current_length += para_length
            else:
                # 如果当前段落太长，截断它
                if current_length < preserve_length * 0.5:  # 如果还有足够空间
                    remaining_space = preserve_length - current_length
                    if remaining_space > 100:  # 至少保留100字符的段落
                        truncated_para = paragraph[:remaining_space-3] + "..."
                        truncated_parts.append(truncated_para)
                break
        
        result = '\n\n'.join(truncated_parts)
        
        # 添加截断提示
        if len(result) < len(content):
            result += f"\n\n[📄 页面内容已截断: 显示 {len(result)}/{len(content)} 字符]"
        
        return result
    
    async def get_page_info(self, page_id: str) -> Dict[str, Any]:
        """获取页面基本信息"""
        # 规范化页面ID
        normalized_id = self._normalize_page_id(page_id)
        
        info = await self.extractor.get_page_basic_info(normalized_id)
        return info or {
            'title': f'页面 {page_id}',
            'url': '',
            'tags': []
        }