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
                parentId=parent_id,
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
        elif block_type == "table":
            # Handle table blocks - extract content from table rows
            text_content = self._extract_table_content(block)
        elif block_type == "table_row":
            # Handle table row blocks - extract content from cells
            text_content = self._extract_table_row_content(block)
        
        return text_content
    
    def _extract_table_content(self, block: Dict[str, Any]) -> str:
        """
        Extract text content from a table block.
        
        Args:
            block: Notion table block object
            
        Returns:
            Formatted table content as string
        """
        try:
            table_data = block.get("table", {})
            table_width = table_data.get("table_width", 0)
            
            # Note: For paginated table content, we need to fetch table rows separately
            # This is a simplified version that handles immediate children
            children = table_data.get("children", [])
            
            if not children:
                return f"[Table with {table_width} columns - content needs separate fetch]"
            
            table_rows = []
            for child in children:
                if child.get("type") == "table_row":
                    row_content = self._extract_table_row_content(child)
                    if row_content:
                        table_rows.append(row_content)
            
            if table_rows:
                return "\n".join(table_rows)
            else:
                return f"[Table with {table_width} columns]"
                
        except Exception as e:
            logger.warning(f"Error extracting table content: {e}")
            return "[Table - extraction failed]"
    
    def _extract_table_row_content(self, block: Dict[str, Any]) -> str:
        """
        Extract text content from a table row block.
        
        Args:
            block: Notion table_row block object
            
        Returns:
            Row content as tab-separated string
        """
        try:
            table_row = block.get("table_row", {})
            cells = table_row.get("cells", [])
            
            cell_texts = []
            for cell in cells:
                # Each cell is an array of rich text objects
                cell_text = ""
                for text_obj in cell:
                    if text_obj.get("type") == "text":
                        cell_text += text_obj.get("text", {}).get("content", "")
                    elif "plain_text" in text_obj:
                        cell_text += text_obj.get("plain_text", "")
                
                cell_texts.append(cell_text.strip())
            
            return " | ".join(cell_texts)
            
        except Exception as e:
            logger.warning(f"Error extracting table row content: {e}")
            return "[Table row - extraction failed]"
    
    async def _extract_text_from_block_recursive(self, block: Dict[str, Any]) -> str:
        """
        Extract text from a block recursively, handling child blocks like table rows.
        
        Args:
            block: Notion block object
            
        Returns:
            Text content including children
        """
        try:
            # Extract text from current block
            text_content = self._extract_text_from_block(block)
            
            # Handle blocks that need child fetching
            block_type = block.get("type", "")
            
            if block_type == "table":
                # For table blocks, we need to fetch the table rows separately
                await self._rate_limit_wait()
                table_id = block.get("id")
                
                if table_id:
                    try:
                        table_rows = await async_collect_paginated_api(
                            self.client.blocks.children.list,
                            block_id=table_id
                        )
                        
                        row_texts = []
                        for row in table_rows:
                            if row.get("type") == "table_row":
                                row_text = self._extract_table_row_content(row)
                                if row_text:
                                    row_texts.append(row_text)
                        
                        if row_texts:
                            return "\n".join(row_texts)
                        else:
                            return text_content  # Fallback to original content
                    except Exception as e:
                        logger.warning(f"Error fetching table rows for block {table_id}: {e}")
                        return text_content  # Fallback to original content
            
            return text_content
            
        except Exception as e:
            logger.warning(f"Error extracting text from block recursively: {e}")
            return self._extract_text_from_block(block)  # Fallback to non-recursive
    
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
                text = await self._extract_text_from_block_recursive(block)
                if text:
                    content_parts.append(text)
            
            return "\n\n".join(content_parts)
            
        except Exception as e:
            error_msg = str(e)
            if "Could not find block with ID" in error_msg:
                logger.warning(f"Page {page_id} not found or not accessible: {e}")
            elif "Make sure the relevant pages and databases are shared" in error_msg:
                logger.warning(f"Permission error for page {page_id}: {e}")
            else:
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
                # 处理文本内容 (包括table)
                text = await self._extract_text_from_block_recursive(block)
                if text:
                    content_parts.append(text)
                
                # 处理文件块
                if block.get("type") == "file":
                    file_content = await self._extract_file_block_content(block)
                    if file_content:
                        content_parts.append(file_content)
            
            return "\n\n".join(content_parts)
            
        except Exception as e:
            error_msg = str(e)
            if "Could not find block with ID" in error_msg:
                logger.warning(f"Page {page_id} not found or not accessible: {e}")
            elif "Make sure the relevant pages and databases are shared" in error_msg:
                logger.warning(f"Permission error for page {page_id}: {e}")
            else:
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
        # 如果已经是UUID格式，直接返回
        if len(page_id) == 36 and page_id.count('-') == 4:
            return page_id
        
        # 移除所有连字符
        clean_id = page_id.replace("-", "")
        
        # 如果长度不是32位，返回原ID（可能是非标准格式）
        if len(clean_id) != 32:
            logger.warning(f"页面ID长度异常: {len(clean_id)} (期望32位) - {page_id}")
            return page_id
        
        # 验证是否为有效的十六进制字符
        try:
            int(clean_id, 16)
        except ValueError:
            logger.warning(f"页面ID包含无效字符: {page_id}")
            return page_id
        
        # 转换为UUID格式: 8-4-4-4-12
        uuid_format = f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:32]}"
        return uuid_format
    
    
    
    async def get_page_info(self, page_id: str) -> Optional[Dict[str, Any]]:
        """获取页面基本信息"""
        # 规范化页面ID
        normalized_id = self._normalize_page_id(page_id)
        
        info = await self.extractor.get_page_basic_info(normalized_id)
        return info  # 如果页面不存在就返回None，不要返回假信息
    
    async def validate_page_structure(self, page_id: str) -> Dict[str, Any]:
        """
        验证页面结构是否适合Deep Research分析
        
        Args:
            page_id: 页面ID
            
        Returns:
            验证结果字典，包含valid, child_count, error等字段
        """
        try:
            # 规范化页面ID
            normalized_id = self._normalize_page_id(page_id)
            
            # 1. 检查页面是否存在
            page_info = await self.extractor.get_page_basic_info(normalized_id)
            if not page_info:
                return {
                    "valid": False,
                    "error": f"页面 {page_id} 不存在或无访问权限",
                    "child_count": 0
                }
            
            # 2. 获取子页面数量
            child_count = await self._count_child_pages(normalized_id)
            
            # 3. 验证是否适合深度研究
            if child_count < 2:
                return {
                    "valid": False,
                    "error": f"页面子页面不足（{child_count}个），至少需要2个子页面才能进行深度研究",
                    "child_count": child_count
                }
            
            return {
                "valid": True,
                "child_count": child_count,
                "page_title": page_info.get("title", "Unknown"),
                "page_url": page_info.get("url", "")
            }
            
        except Exception as e:
            logger.error(f"页面结构验证失败 {page_id}: {e}")
            return {
                "valid": False,
                "error": f"验证过程出错: {str(e)}",
                "child_count": 0
            }
    
    async def _count_child_pages(self, page_id: str) -> int:
        """
        计算页面的直接子页面数量
        
        Args:
            page_id: 页面ID
            
        Returns:
            子页面数量
        """
        try:
            await self.extractor._rate_limit_wait()
            
            # 获取页面的所有子块
            blocks = await self.extractor.client.blocks.children.list(
                block_id=page_id,
                page_size=100  # 足够获取大部分子页面
            )
            
            child_page_count = 0
            for block in blocks.get("results", []):
                if block.get("type") == "child_page":
                    child_page_count += 1
            
            # 如果有更多页面，继续获取
            if blocks.get("has_more", False):
                next_cursor = blocks.get("next_cursor")
                while next_cursor:
                    await self.extractor._rate_limit_wait()
                    next_blocks = await self.extractor.client.blocks.children.list(
                        block_id=page_id,
                        start_cursor=next_cursor,
                        page_size=100
                    )
                    
                    for block in next_blocks.get("results", []):
                        if block.get("type") == "child_page":
                            child_page_count += 1
                    
                    if next_blocks.get("has_more", False):
                        next_cursor = next_blocks.get("next_cursor")
                    else:
                        break
            
            return child_page_count
            
        except Exception as e:
            logger.warning(f"计算子页面数量失败 {page_id}: {e}")
            return 0
    
    async def get_child_pages_bfs(self, root_page_id: str, max_depth: int = 3, max_pages: int = 20) -> List[Dict[str, Any]]:
        """
        BFS遍历获取子页面结构
        
        Args:
            root_page_id: 根页面ID
            max_depth: 最大遍历深度
            max_pages: 最大页面数限制
            
        Returns:
            页面元数据列表，包含层级信息
        """
        try:
            normalized_root_id = self._normalize_page_id(root_page_id)
            
            # BFS队列：(page_id, depth, parent_id)
            queue = [(normalized_root_id, 0, None)]
            visited = set()
            result_pages = []
            
            while queue and len(result_pages) < max_pages:  # 限制最大页面数
                current_page_id, current_depth, parent_id = queue.pop(0)
                
                if current_page_id in visited or current_depth > max_depth:
                    continue
                    
                visited.add(current_page_id)
                
                # 获取当前页面信息
                page_info = await self.extractor.get_page_basic_info(current_page_id)
                if not page_info:
                    continue
                
                # 添加到结果（跳过根页面）
                if current_depth > 0:
                    page_metadata = {
                        "notion_id": current_page_id,
                        "title": page_info["title"],
                        "url": page_info["url"],
                        "tags": page_info.get("tags", []),
                        "last_edited_time": page_info["last_edited_time"],
                        "depth": current_depth,
                        "parent_id": parent_id
                    }
                    result_pages.append(page_metadata)
                
                # 如果还没达到最大深度，获取子页面
                if current_depth < max_depth:
                    child_pages = await self._get_direct_child_pages(current_page_id)
                    for child_id in child_pages:
                        if child_id not in visited:
                            queue.append((child_id, current_depth + 1, current_page_id))
            
            logger.info(f"BFS遍历完成：从 {root_page_id} 获取 {len(result_pages)} 个页面（深度≤{max_depth}）")
            return result_pages
            
        except Exception as e:
            logger.error(f"BFS遍历失败 {root_page_id}: {e}")
            return []
    
    async def _get_direct_child_pages(self, page_id: str) -> List[str]:
        """
        获取页面的直接子页面ID列表
        
        Args:
            page_id: 页面ID
            
        Returns:
            子页面ID列表
        """
        try:
            child_page_ids = []
            
            await self.extractor._rate_limit_wait()
            blocks = await self.extractor.client.blocks.children.list(
                block_id=page_id,
                page_size=100
            )
            
            # 处理第一页结果
            for block in blocks.get("results", []):
                if block.get("type") == "child_page":
                    child_page_ids.append(block["id"])
            
            # 处理分页结果
            while blocks.get("has_more", False):
                await self.extractor._rate_limit_wait()
                blocks = await self.extractor.client.blocks.children.list(
                    block_id=page_id,
                    start_cursor=blocks.get("next_cursor"),
                    page_size=100
                )
                
                for block in blocks.get("results", []):
                    if block.get("type") == "child_page":
                        child_page_ids.append(block["id"])
            
            return child_page_ids
            
        except Exception as e:
            logger.warning(f"获取直接子页面失败 {page_id}: {e}")
            return []
    
