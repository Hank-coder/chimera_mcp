"""
Notion Webhook处理器
实现实时响应Notion页面变更的webhook处理逻辑
"""

import asyncio
import json
import hmac
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger

from core.graphiti_client import GraphitiClient
from core.notion_client import NotionExtractor
from core.models import NotionPageMetadata, NodeType, extract_title_from_page, extract_tags_from_page, extract_parent_id_from_page
from core.embedding_service import generate_page_embedding, extract_structured_headings
from config.settings import get_settings


class NotionWebhookHandler:
    """
    Notion Webhook事件处理器
    处理page.created, page.moved, page.properties_updated, page.deleted事件
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.graph_client = None
        self.notion_client = None
        self._initialized = False
        
        # Webhook签名验证密钥
        self.webhook_secret = self.settings.NOTION_WEBHOOK_SECRET
    
    async def initialize(self):
        """初始化客户端"""
        if self._initialized:
            return
            
        try:
            self.graph_client = GraphitiClient()
            await self.graph_client.initialize()
            
            self.notion_client = NotionExtractor(
                api_key=self.settings.notion_token,
                rate_limit_per_second=self.settings.notion_rate_limit_per_second
            )
            
            self._initialized = True
            logger.info("Webhook handler initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize webhook handler: {e}")
            raise
    
    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        """
        验证webhook签名
        
        Args:
            body: 请求体字节
            signature: Notion发送的签名
            
        Returns:
            True if signature is valid, False otherwise
        """
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured, skipping signature verification")
            return True
            
        try:
            # Notion使用HMAC-SHA256
            expected_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                body,
                hashlib.sha256
            ).hexdigest()
            
            # 比较签名（防止时序攻击）
            return hmac.compare_digest(signature, expected_signature)
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}")
            return False
    
    async def handle_webhook_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理webhook事件的主入口
        
        Args:
            event_data: Webhook事件数据
            
        Returns:
            处理结果
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            event_type = event_data.get('type')
            entity = event_data.get('entity', {})
            page_id = entity.get('id')
            
            if not event_type or not page_id:
                logger.warning(f"Invalid webhook event: missing type or page_id")
                return {"success": False, "error": "Invalid event data"}
            
            logger.info(f"Processing webhook event: {event_type} for page {page_id}")
            
            # 根据事件类型分发处理
            if event_type == 'page.created':
                result = await self._handle_page_created(event_data)
            elif event_type == 'page.moved':
                result = await self._handle_page_moved(event_data)
            elif event_type == 'page.properties_updated':
                result = await self._handle_page_properties_updated(event_data)
            elif event_type == 'page.deleted':
                result = await self._handle_page_deleted(event_data)
            elif event_type == 'page.content_updated':
                result = await self._handle_page_content_updated(event_data)
            else:
                logger.warning(f"Unsupported event type: {event_type}")
                result = {"success": False, "error": f"Unsupported event type: {event_type}"}
            
            # 如果处理成功，更新JSON缓存和embedding
            if result.get("success", False):
                await self._update_json_cache()

                # 🆕 智能检查是否需要更新embedding
                page_id = event_data.get('entity', {}).get('id')
                if page_id:
                    should_update = await self._should_update_embedding(page_id, event_type, event_data)
                    if should_update:
                        await self._handle_embedding_update(page_id, event_type)

            return result
            
        except Exception as e:
            logger.exception(f"Error handling webhook event: {e}")
            
            # 记录详细错误信息
            error_details = {
                "event_type": event_data.get("type", "unknown"),
                "entity_id": event_data.get("entity", {}).get("id", "unknown"),
                "error_message": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.now().isoformat(),
                "event_data": event_data
            }
            logger.error(f"❌ [Webhook处理器错误详情] {json.dumps(error_details, indent=2, ensure_ascii=False)}")
            
            return {"success": False, "error": str(e), "error_type": type(e).__name__}
    
    async def _handle_page_created(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理页面创建事件
        算法：MERGE 节点；连父关系
        """
        page_id = event_data['entity']['id']
        
        try:
            async with self.graph_client._driver.session() as session:
                tx = await session.begin_transaction()
                try:
                    # 1. 获取页面详细信息
                    page_data = await self.notion_client.client.pages.retrieve(page_id=page_id)
                    
                    # 2. 提取页面元数据
                    metadata = await self._extract_page_metadata(page_data)
                    if not metadata:
                        raise Exception(f"Failed to extract metadata for page {page_id}")
                    
                    # 3. MERGE页面节点
                    await self._upsert_page_in_transaction(tx, metadata)
                    
                    # 4. 创建父子关系
                    if metadata.parentId:
                        await self._create_parent_relationship_in_transaction(
                            tx, page_id, metadata.parentId
                        )
                    
                    # 5. 创建其他关系（标签、内链等）
                    await self._create_relationships_in_transaction(tx, metadata)
                    
                    await tx.commit()
                except Exception as e:
                    await tx.rollback()
                    raise
                    
            logger.info(f"✅ Page created: {metadata.title} ({page_id})")
            return {
                "success": True, 
                "action": "page_created",
                "page_id": page_id,
                "title": metadata.title
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to handle page created: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_page_moved(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理页面移动事件
        算法：改父关系；重算自身路径；对子树路径做前缀替换
        """
        page_id = event_data['entity']['id']
        data = event_data.get('data', {})
        new_parent_data = data.get('parent', {})
        new_parent_id = new_parent_data.get('id') if new_parent_data.get('type') == 'page' else None
        
        try:
            async with self.graph_client._driver.session() as session:
                tx = await session.begin_transaction()
                try:
                    # 1. 删除旧的父子关系
                    await tx.run("""
                        MATCH (p:NotionPage {notionId: $page_id})-[r:CHILD_OF]->()
                        DELETE r
                    """, page_id=page_id)
                    
                    # 2. 创建新的父子关系
                    if new_parent_id:
                        await self._create_parent_relationship_in_transaction(
                            tx, page_id, new_parent_id
                        )
                    
                    # 3. 重新计算页面层级
                    new_level = await self._calculate_page_level_in_transaction(
                        tx, new_parent_id
                    ) if new_parent_id else 0
                    
                    await tx.run("""
                        MATCH (p:NotionPage {notionId: $page_id})
                        SET p.level = $level, p.updatedAt = datetime()
                    """, page_id=page_id, level=new_level)
                    
                    # 4. 更新子树的层级（级联更新）
                    await self._update_subtree_levels_in_transaction(tx, page_id, new_level)
                    
                    await tx.commit()
                except Exception as e:
                    await tx.rollback()
                    raise
                    
            logger.info(f"✅ Page moved: {page_id} to parent {new_parent_id}")
            return {
                "success": True,
                "action": "page_moved", 
                "page_id": page_id,
                "new_parent_id": new_parent_id,
                "new_level": new_level
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to handle page moved: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_page_properties_updated(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理页面属性更新事件
        算法：改标题；依父路径重算前缀；更新子树路径
        """
        page_id = event_data['entity']['id']
        data = event_data.get('data', {})
        updated_properties = data.get('updated_properties', [])
        
        try:
            async with self.graph_client._driver.session() as session:
                tx = await session.begin_transaction()
                try:
                    # 1. 获取更新后的页面信息
                    page_data = await self.notion_client.client.pages.retrieve(page_id=page_id)
                    
                    # 2. 提取新的元数据
                    metadata = await self._extract_page_metadata(page_data)
                    if not metadata:
                        raise Exception(f"Failed to extract metadata for page {page_id}")
                    
                    # 3. 更新页面属性
                    await tx.run("""
                        MATCH (p:NotionPage {notionId: $notionId})
                        SET p.title = $title,
                            p.tags = $tags,
                            p.lastEditedTime = $lastEditedTime,
                            p.updatedAt = datetime()
                    """, 
                        notionId=page_id,
                        title=metadata.title,
                        tags=metadata.tags,
                        lastEditedTime=metadata.last_edited_time
                    )
                    
                    # 4. 如果标题更新了，可能需要更新相关关系
                    if 'title' in updated_properties:
                        # 重新创建基于标题的关系（如内链）
                        await self._recreate_title_based_relationships_in_transaction(tx, metadata)
                    
                    await tx.commit()
                except Exception as e:
                    await tx.rollback()
                    raise
                    
            logger.info(f"✅ Page properties updated: {metadata.title} ({page_id})")
            return {
                "success": True,
                "action": "page_properties_updated",
                "page_id": page_id,
                "updated_properties": updated_properties,
                "new_title": metadata.title
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to handle page properties updated: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_page_deleted(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理页面删除事件
        算法：级联删除所有子页面和子页面的子页面
        """
        page_id = event_data['entity']['id']
        
        try:
            async with self.graph_client._driver.session() as session:
                tx = await session.begin_transaction()
                try:
                    # 1. 收集要删除的所有页面（包括所有层级的子页面）
                    result = await tx.run("""
                        MATCH (p:NotionPage {notionId: $page_id})
                        OPTIONAL MATCH (p)<-[:CHILD_OF*]-(descendant:NotionPage)
                        RETURN p.title as title, 
                               collect(DISTINCT descendant.notionId) as all_descendant_ids,
                               collect(DISTINCT descendant.title) as all_descendant_titles
                    """, page_id=page_id)
                    
                    record = await result.single()
                    if not record:
                        logger.warning(f"Page {page_id} not found in graph")
                        return {"success": True, "note": "Page already deleted from graph"}
                    
                    title = record['title']
                    all_descendant_ids = record['all_descendant_ids'] or []
                    all_descendant_titles = record['all_descendant_titles'] or []
                    
                    # 过滤掉空值
                    all_descendant_ids = [id for id in all_descendant_ids if id]
                    all_descendant_titles = [title for title in all_descendant_titles if title]
                    
                    if all_descendant_ids:
                        logger.info(f"Page {page_id} has {len(all_descendant_ids)} descendants, will cascade delete all")
                        logger.debug(f"Descendants to delete: {all_descendant_titles}")
                    
                    # 2. 级联删除：删除页面及其所有子页面（包括多层嵌套）
                    delete_result = await tx.run("""
                        MATCH (p:NotionPage {notionId: $page_id})
                        OPTIONAL MATCH (p)<-[:CHILD_OF*]-(descendant:NotionPage)
                        WITH p, collect(DISTINCT descendant) as descendants
                        WITH p + descendants as all_nodes
                        UNWIND all_nodes as node
                        DETACH DELETE node
                        RETURN count(node) as total_deleted
                    """, page_id=page_id)
                    
                    delete_summary = await delete_result.single()
                    total_deleted = delete_summary['total_deleted'] if delete_summary else 1
                    
                    await tx.commit()
                except Exception as e:
                    await tx.rollback()
                    raise
                    
            logger.info(f"✅ Page deleted: {title} ({page_id}), cascade deleted {total_deleted} total pages")
            return {
                "success": True,
                "action": "page_deleted",
                "page_id": page_id,
                "title": title,
                "total_deleted": total_deleted,
                "descendant_count": len(all_descendant_ids)
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to handle page deleted: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_page_content_updated(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理页面内容更新事件
        算法：更新最后修改时间，不更新图谱结构
        """
        page_id = event_data['entity']['id']
        
        try:
            async with self.graph_client._driver.session() as session:
                tx = await session.begin_transaction()
                try:
                    # 1. 获取页面最新信息
                    page_data = await self.notion_client.client.pages.retrieve(page_id=page_id)
                    last_edited_time = datetime.fromisoformat(page_data["last_edited_time"].replace("Z", "+00:00"))
                    
                    # 2. 只更新最后修改时间，不改动图谱结构
                    await tx.run("""
                        MATCH (p:NotionPage {notionId: $page_id})
                        SET p.lastEditedTime = $lastEditedTime,
                            p.updatedAt = datetime()
                    """, page_id=page_id, lastEditedTime=last_edited_time)
                    
                    await tx.commit()
                except Exception as e:
                    await tx.rollback()
                    raise
                    
            logger.info(f"✅ Page content updated: {page_id} - last edited time updated")
            return {
                "success": True,
                "action": "page_content_updated",
                "page_id": page_id,
                "last_edited_time": last_edited_time.isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to handle page content updated: {e}")
            return {"success": False, "error": str(e)}
    
    async def _extract_page_metadata(self, page_data: Dict[str, Any]) -> Optional[NotionPageMetadata]:
        """提取页面元数据"""
        try:
            notion_id = page_data["id"]
            title = extract_title_from_page(page_data)
            tags = extract_tags_from_page(page_data)
            last_edited_time = datetime.fromisoformat(page_data["last_edited_time"].replace("Z", "+00:00"))
            url = page_data["url"]
            parent_id = extract_parent_id_from_page(page_data)
            
            # 提取关系（简化版，主要处理父子关系）
            internal_links, mentions = await self.notion_client._extract_relationships_from_content(notion_id)
            database_relations = self.notion_client._extract_database_relations(page_data)
            level = await self._calculate_page_level_async(parent_id) if parent_id else 0
            
            return NotionPageMetadata(
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
            
        except Exception as e:
            logger.error(f"Error extracting page metadata: {e}")
            return None
    
    async def _calculate_page_level_async(self, parent_id: str, max_depth: int = 10) -> int:
        """异步计算页面层级"""
        if not parent_id or max_depth <= 0:
            return 0
            
        try:
            parent_page = await self.notion_client.client.pages.retrieve(page_id=parent_id)
            parent_parent_id = extract_parent_id_from_page(parent_page)
            
            if parent_parent_id:
                parent_level = await self._calculate_page_level_async(parent_parent_id, max_depth - 1)
                return parent_level + 1
            else:
                return 1
                
        except Exception as e:
            logger.warning(f"Could not calculate level for parent {parent_id}: {e}")
            return 1
    
    async def _upsert_page_in_transaction(self, tx, metadata: NotionPageMetadata):
        """在事务中更新或创建页面"""
        await tx.run("""
            MERGE (p:NotionPage {notionId: $notionId})
            SET p.title = $title,
                p.type = $type,
                p.tags = $tags,
                p.lastEditedTime = $lastEditedTime,
                p.url = $url,
                p.parentId = $parentId,
                p.level = $level,
                p.updatedAt = datetime()
        """,
            notionId=metadata.notion_id,
            title=metadata.title,
            type=metadata.type.value,
            tags=metadata.tags,
            lastEditedTime=metadata.last_edited_time,
            url=metadata.url,
            parentId=metadata.parentId,
            level=metadata.level
        )
    
    async def _create_parent_relationship_in_transaction(self, tx, page_id: str, parent_id: str):
        """在事务中创建父子关系，带验证"""
        # 首先验证两个节点都存在
        verification_result = await tx.run("""
            MATCH (child:NotionPage {notionId: $page_id})
            OPTIONAL MATCH (parent:NotionPage {notionId: $parent_id})
            RETURN child.title as child_title, parent.title as parent_title
        """, page_id=page_id, parent_id=parent_id)
        
        record = await verification_result.single()
        if not record:
            raise Exception(f"Child page {page_id} not found in graph")
        
        if not record["parent_title"]:
            # 父页面不存在，先尝试从 Notion API 获取并创建
            logger.warning(f"Parent page {parent_id} not found for child {record['child_title']}, attempting to fetch from Notion")
            
            try:
                # 从 Notion API 获取父页面
                parent_page_data = await self.notion_client.client.pages.retrieve(page_id=parent_id)
                parent_metadata = await self._extract_page_metadata(parent_page_data)
                
                if parent_metadata:
                    # 创建父页面
                    await self._upsert_page_in_transaction(tx, parent_metadata)
                    logger.info(f"Successfully created missing parent page: {parent_metadata.title}")
                    
                    # 如果父页面也有父页面，递归创建关系
                    if parent_metadata.parentId:
                        try:
                            await self._create_parent_relationship_in_transaction(
                                tx, parent_id, parent_metadata.parentId
                            )
                        except Exception as e:
                            logger.warning(f"Failed to create grandparent relationship for {parent_metadata.title}: {e}")
                else:
                    raise Exception(f"Failed to extract metadata for parent page {parent_id}")
                    
            except Exception as e:
                raise Exception(f"Cannot create CHILD_OF relationship: parent page {parent_id} not found and cannot be fetched from Notion: {e}")
        
        # 现在创建关系
        await tx.run("""
            MATCH (child:NotionPage {notionId: $page_id})
            MATCH (parent:NotionPage {notionId: $parent_id})
            MERGE (child)-[:CHILD_OF]->(parent)
        """, page_id=page_id, parent_id=parent_id)
        
        logger.debug(f"Created CHILD_OF relationship: {record['child_title']} -> {record.get('parent_title', 'parent')}")
    
    async def _create_relationships_in_transaction(self, tx, metadata: NotionPageMetadata):
        """在事务中创建其他关系"""
        # 创建标签关系
        for tag in metadata.tags:
            await tx.run("""
                MATCH (page:NotionPage {notionId: $page_id})
                MERGE (tag:Tag {name: $tag})
                MERGE (page)-[:HAS_TAG]->(tag)
            """, page_id=metadata.notion_id, tag=tag)
        
        # 其他关系创建逻辑可以后续添加...
    
    async def _calculate_page_level_in_transaction(self, tx, parent_id: str) -> int:
        """在事务中计算页面层级"""
        if not parent_id:
            return 0
            
        result = await tx.run("""
            MATCH (p:NotionPage {notionId: $parent_id})
            RETURN p.level as parent_level
        """, parent_id=parent_id)
        
        record = await result.single()
        if record:
            return record['parent_level'] + 1
        else:
            return 1
    
    async def _update_subtree_levels_in_transaction(self, tx, root_page_id: str, root_level: int):
        """在事务中更新子树的层级"""
        # 递归更新所有子页面的层级
        await tx.run("""
            MATCH path = (root:NotionPage {notionId: $root_id})<-[:CHILD_OF*]-(descendant:NotionPage)
            WITH root, descendant, length(path) as depth
            SET descendant.level = $root_level + depth,
                descendant.updatedAt = datetime()
        """, root_id=root_page_id, root_level=root_level)
    
    async def _recreate_title_based_relationships_in_transaction(self, tx, metadata: NotionPageMetadata):
        """在事务中重新创建基于标题的关系"""
        # 当标题更新时，可能需要更新基于标题的内链等关系
        # 这里先简单处理，后续可以扩展
        logger.info(f"Title-based relationships update for {metadata.notion_id} - {metadata.title}")
    
    async def _update_json_cache(self):
        """更新JSON缓存"""
        try:
            # 重新生成JSON缓存以反映Neo4j中的最新变化
            import json
            from pathlib import Path
            from datetime import datetime
            
            logger.info("🔄 重新生成JSON缓存以反映最新变化...")
            
            # 使用与manual_sync.py相同的缓存生成逻辑
            cache_data = await self._build_cache_data()
            
            # 写入缓存文件
            cache_dir = Path("llm_cache")
            cache_dir.mkdir(exist_ok=True)
            cache_file = cache_dir / "chimera_cache.json"
            
            self._write_cache_file(cache_file, cache_data)
            
            logger.info(f"✅ JSON缓存已更新：{cache_data['metadata']['total_pages']} 页面，{cache_data['metadata']['total_paths']} 路径")
                
        except Exception as e:
            logger.error(f"Failed to update JSON cache: {e}")
    
    async def _build_cache_data(self):
        """构建缓存数据（与manual_sync.py中的逻辑相同）"""
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
        
        async with self.graph_client._driver.session() as session:
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
        cache_data["paths"] = self._build_paths(pages_map)
        cache_data["metadata"]["total_pages"] = len(cache_data["pages"])
        cache_data["metadata"]["total_paths"] = len(cache_data["paths"])
        
        return cache_data
    
    def _build_paths(self, pages_map):
        """构建完整路径（与manual_sync.py中的逻辑相同）"""
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
                actual_path_length = len(path_ids) - 1
                paths.append({
                    "path_string": path_string,
                    "path_titles": path_titles,
                    "path_ids": path_ids,
                    "leaf_id": leaf_id,
                    "leaf_title": pages_map[leaf_id]["title"],
                    "leaf_last_edited_time": pages_map[leaf_id]["lastEditedTime"],
                    "path_length": actual_path_length
                })
        
        return paths
    
    def _write_cache_file(self, cache_file, cache_data):
        """写入缓存文件（与manual_sync.py中的逻辑相同）"""
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

    async def _should_update_embedding(self, page_id: str, event_type: str, event_data: dict) -> bool:
        """
        智能判断是否需要更新embedding
        只有在页面标题或一二级标题变化时才更新embedding

        触发条件：
        1. page.created - 新建页面
        2. page.properties_updated - 页面属性更新（通常是标题）
        3. page.content_updated - 仅当涉及标题内容的变化
        """
        try:
            # 1. 新建页面总是需要生成embedding
            if event_type == 'page.created':
                logger.debug(f"页面 {page_id} 新建，需要生成embedding")
                return True

            # 2. 页面属性更新（通常是标题变化）
            if event_type == 'page.properties_updated':
                logger.debug(f"页面 {page_id} 属性更新，可能是标题变化，需要更新embedding")
                return True

            # 3. 页面内容更新 - 需要进一步判断是否涉及标题
            if event_type == 'page.content_updated':
                # 获取当前页面的结构化标题
                from core.embedding_service import extract_structured_headings

                try:
                    current_structured = await extract_structured_headings(page_id)
                    if not current_structured:
                        logger.debug(f"页面 {page_id} 无法提取结构化标题，跳过embedding更新")
                        return False

                    # 获取数据库中已存储的embedding文本
                    async with self.graph_client._driver.session() as session:
                        result = await session.run("""
                            MATCH (p:NotionPage {notionId: $page_id})
                            RETURN p.geminiEmbeddingText as stored_text
                        """, {"page_id": page_id})

                        record = await result.single()
                        if not record or not record.get('stored_text'):
                            logger.debug(f"页面 {page_id} 没有已存储的embedding文本，需要生成")
                            return True

                        stored_text = record['stored_text']

                    # 生成当前的embedding文本
                    from core.embedding_service import format_structured_text_for_embedding
                    current_text = format_structured_text_for_embedding(current_structured)

                    # 比较标题内容是否发生变化
                    if current_text != stored_text:
                        logger.info(f"页面 {page_id} 标题内容发生变化，需要更新embedding")
                        logger.debug(f"旧文本: {stored_text}")
                        logger.debug(f"新文本: {current_text}")
                        return True
                    else:
                        logger.debug(f"页面 {page_id} 标题内容未变化，无需更新embedding")
                        return False

                except Exception as e:
                    logger.warning(f"页面 {page_id} 标题变化检测失败: {e}，默认更新embedding")
                    return True

            # 4. 其他事件类型不触发embedding更新
            logger.debug(f"页面 {page_id} 事件类型 {event_type} 不触发embedding更新")
            return False

        except Exception as e:
            logger.error(f"判断页面 {page_id} 是否需要更新embedding时出错: {e}")
            # 出错时默认更新，确保不遗漏
            return True

    async def _handle_embedding_update(self, page_id: str, event_type: str):
        """
        处理embedding更新逻辑
        检查页面是否需要更新embedding，如果需要则生成新的embedding
        """
        try:
            logger.info(f"🧠 检查页面 {page_id} 是否需要更新embedding (事件类型: {event_type})")

            # 1. 检查是否需要更新embedding
            needs_update = await self._check_if_embedding_needed(page_id)

            if not needs_update:
                logger.debug(f"页面 {page_id} 不需要更新embedding")
                return

            logger.info(f"🧠 页面 {page_id} 需要更新embedding，开始生成...")

            # 2. 生成新的embedding
            embedding_vector, embedding_text = await generate_page_embedding(page_id)

            if embedding_vector and embedding_text:
                # 3. 更新到Neo4j
                success = await self._update_page_embedding_in_neo4j(
                    page_id, embedding_vector, embedding_text
                )

                if success:
                    logger.info(f"✅ 页面 {page_id} embedding更新成功 (维度: {len(embedding_vector)})")
                else:
                    logger.error(f"❌ 页面 {page_id} embedding更新到Neo4j失败")
            else:
                logger.warning(f"⚠️ 页面 {page_id} embedding生成失败")

        except Exception as e:
            logger.error(f"❌ 处理页面 {page_id} embedding更新时出错: {e}")

    async def _check_if_embedding_needed(self, page_id: str) -> bool:
        """
        检查页面是否需要更新embedding
        判断条件：
        1. embedding为空
        2. 页面编辑时间晚于embedding更新时间
        3. 标题或一二级标题发生变化
        """
        try:
            async with self.graph_client._driver.session() as session:
                query = """
                MATCH (p:NotionPage {notionId: $page_id})
                RETURN p.geminiEmbedding IS NULL as needs_embedding,
                       p.geminiEmbeddingUpdatedAt as last_embedding_updated,
                       p.lastEditedTime as last_edited,
                       p.title as current_title,
                       p.geminiEmbeddingText as current_embedding_text
                """

                result = await session.run(query, page_id=page_id)
                record = await result.single()

                if not record:
                    logger.debug(f"页面 {page_id} 在图谱中不存在，需要embedding")
                    return True

                # 如果embedding为空，需要更新
                if record['needs_embedding']:
                    logger.debug(f"页面 {page_id} embedding为空，需要更新")
                    return True

                # 如果页面编辑时间晚于embedding更新时间，需要更新
                last_edited = record['last_edited']
                last_embedding_updated = record['last_embedding_updated']

                if last_edited and last_embedding_updated and last_edited > last_embedding_updated:
                    logger.debug(f"页面 {page_id} 编辑时间({last_edited})晚于embedding更新时间({last_embedding_updated})，需要更新")
                    return True

                # 如果没有embedding更新时间记录，但有embedding，说明是旧数据，需要更新
                if not last_embedding_updated and not record['needs_embedding']:
                    logger.debug(f"页面 {page_id} 缺少embedding更新时间记录，需要更新")
                    return True

                logger.debug(f"页面 {page_id} embedding是最新的，无需更新")
                return False

        except Exception as e:
            logger.error(f"检查页面 {page_id} embedding需求时出错: {e}")
            return True  # 出错时默认需要更新

    async def _update_page_embedding_in_neo4j(self, page_id: str, embedding_vector: List[float], embedding_text: str) -> bool:
        """
        更新页面的embedding到Neo4j
        """
        try:
            async with self.graph_client._driver.session() as session:
                query = """
                MATCH (p:NotionPage {notionId: $page_id})
                SET p.geminiEmbedding = $embedding_vector,
                    p.geminiEmbeddingText = $embedding_text,
                    p.geminiEmbeddingUpdatedAt = datetime()
                RETURN p.title as title
                """

                result = await session.run(
                    query,
                    page_id=page_id,
                    embedding_vector=embedding_vector,
                    embedding_text=embedding_text
                )

                record = await result.single()
                if record:
                    title = record['title']
                    logger.debug(f"成功更新页面 '{title}' ({page_id}) 的embedding到Neo4j")
                    return True
                else:
                    logger.error(f"页面 {page_id} 在Neo4j中不存在，无法更新embedding")
                    return False

        except Exception as e:
            logger.error(f"更新页面 {page_id} embedding到Neo4j时出错: {e}")
            return False


# 工厂函数
async def create_webhook_handler() -> NotionWebhookHandler:
    """创建并初始化webhook处理器"""
    handler = NotionWebhookHandler()
    await handler.initialize()
    return handler