import asyncio
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime
import json
from loguru import logger
from neo4j import AsyncGraphDatabase

from .models import (
    NotionPageMetadata,
    RelationType,
    SearchResult,
    ExpandResult,
    GraphStats
)
from config.settings import settings


class GraphitiClient:
    """
    简化的Neo4j客户端，用于Notion页面索引。
    移除embedding功能，使用简单的文本搜索和图遍历。
    """
    
    def __init__(self, neo4j_uri: str = None, neo4j_user: str = None, neo4j_password: str = None):
        """
        Initialize Neo4j client connection.
        
        Args:
            neo4j_uri: Neo4j connection URI (defaults to settings)
            neo4j_user: Neo4j username (defaults to settings)
            neo4j_password: Neo4j password (defaults to settings)
        """
        self.neo4j_uri = neo4j_uri or settings.neo4j_uri
        self.neo4j_user = neo4j_user or settings.neo4j_username
        self.neo4j_password = neo4j_password or settings.neo4j_password
        self._driver = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the Neo4j client."""
        if self._initialized:
            return
            
        try:
            self._driver = AsyncGraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password)
            )
            
            # 创建索引和约束
            await self._create_indices_and_constraints()
            self._initialized = True
            logger.info("Neo4j client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Neo4j client: {e}")
            raise
    
    async def close(self):
        """Close the Neo4j client."""
        if self._driver and self._initialized:
            await self._driver.close()
            self._initialized = False
            logger.info("Neo4j client closed")
    
    async def _create_indices_and_constraints(self):
        """创建必要的索引和约束（不包含embedding）"""
        async with self._driver.session() as session:
            # 创建 NotionPage 唯一约束
            await session.run("""
                CREATE CONSTRAINT notion_page_id IF NOT EXISTS
                FOR (p:NotionPage) REQUIRE p.notionId IS UNIQUE
            """)
            
            # 创建标题索引用于搜索
            await session.run("""
                CREATE INDEX notion_page_title IF NOT EXISTS
                FOR (p:NotionPage) ON (p.title)
            """)
            
            # 创建最后编辑时间索引用于增量同步
            await session.run("""
                CREATE INDEX notion_page_last_edited IF NOT EXISTS
                FOR (p:NotionPage) ON (p.lastEditedTime)
            """)
            
            # 创建层级索引用于深度查询
            await session.run("""
                CREATE INDEX notion_page_level IF NOT EXISTS
                FOR (p:NotionPage) ON (p.level)
            """)
            
            logger.info("Created indices and constraints for NotionPage")
    
    async def upsert_page(self, page_metadata: NotionPageMetadata) -> bool:
        """
        Upsert a NotionPage node in the graph (without embedding).
        
        Args:
            page_metadata: Page metadata to upsert
            
        Returns:
            True if successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        try:
            async with self._driver.session() as session:
                query = """
                MERGE (p:NotionPage {notionId: $notionId})
                SET p.title = $title,
                    p.type = $type,
                    p.tags = $tags,
                    p.lastEditedTime = $lastEditedTime,
                    p.url = $url,
                    p.parentId = $parentId,
                    p.level = $level,
                    p.updatedAt = datetime()
                RETURN p.notionId as id
                """
                
                result = await session.run(
                    query,
                    notionId=page_metadata.notion_id,
                    title=page_metadata.title,
                    type=page_metadata.type.value,
                    tags=page_metadata.tags,
                    lastEditedTime=page_metadata.last_edited_time,
                    url=page_metadata.url,
                    parentId=page_metadata.parent_id,
                    level=page_metadata.level
                )
                
                record = await result.single()
                if record:
                    logger.debug(f"Upserted NotionPage: {page_metadata.title} ({page_metadata.notion_id})")
                    return True
                else:
                    logger.error(f"Failed to upsert page {page_metadata.notion_id}")
                    return False
            
        except Exception as e:
            logger.error(f"Error upserting page {page_metadata.notion_id}: {e}")
            return False
    
    async def create_relationships(self, page_metadata: NotionPageMetadata) -> bool:
        """
        Create relationships for a page based on its metadata.
        
        Args:
            page_metadata: Page metadata containing relationship information
            
        Returns:
            True if successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        try:
            async with self._driver.session() as session:
                # Create CHILD_OF relationship
                if page_metadata.parent_id:
                    await self._create_relationship(
                        session,
                        page_metadata.notion_id,
                        page_metadata.parent_id,
                        RelationType.CHILD_OF
                    )
                
                # Create LINKS_TO relationships
                for link in page_metadata.internal_links:
                    target_id = await self._find_page_by_title(session, link)
                    if target_id:
                        await self._create_relationship(
                            session,
                            page_metadata.notion_id,
                            target_id,
                            RelationType.LINKS_TO
                        )
                
                # Create MENTIONS relationships
                for mention in page_metadata.mentions:
                    target_id = await self._find_page_by_title(session, mention)
                    if target_id:
                        await self._create_relationship(
                            session,
                            page_metadata.notion_id,
                            target_id,
                            RelationType.MENTIONS
                        )
                
                # Create RELATED_TO relationships
                for relation_id in page_metadata.database_relations:
                    await self._create_relationship(
                        session,
                        page_metadata.notion_id,
                        relation_id,
                        RelationType.RELATED_TO
                    )
                
                # Create HAS_TAG relationships
                for tag in page_metadata.tags:
                    await self._create_tag_relationship(session, page_metadata.notion_id, tag)
                
                logger.debug(f"Created relationships for page {page_metadata.notion_id}")
                return True
            
        except Exception as e:
            logger.error(f"Error creating relationships for page {page_metadata.notion_id}: {e}")
            return False
    
    async def _create_relationship(self, session, source_id: str, target_id: str, relation_type: RelationType):
        """Create a relationship between two pages."""
        query = f"""
        MATCH (source:NotionPage {{notionId: $source_id}})
        MATCH (target:NotionPage {{notionId: $target_id}})
        MERGE (source)-[r:{relation_type.value}]->(target)
        SET r.createdAt = datetime()
        """
        
        await session.run(
            query,
            source_id=source_id,
            target_id=target_id
        )
    
    async def _create_tag_relationship(self, session, page_id: str, tag: str):
        """Create a relationship between a page and a tag."""
        query = """
        MATCH (page:NotionPage {notionId: $page_id})
        MERGE (tag:Tag {name: $tag})
        MERGE (page)-[r:HAS_TAG]->(tag)
        SET r.createdAt = datetime()
        """
        
        await session.run(
            query,
            page_id=page_id,
            tag=tag
        )
    
    async def _find_page_by_title(self, session, title: str) -> Optional[str]:
        """Find a page ID by its title."""
        query = """
        MATCH (p:NotionPage)
        WHERE p.title CONTAINS $title
        RETURN p.notionId
        LIMIT 1
        """
        
        result = await session.run(query, title=title)
        record = await result.single()
        if record:
            return record["p.notionId"]
        return None
    
    async def search_by_query(self, query: str, limit: int = 10) -> List[SearchResult]:
        """
        使用文本搜索查找相关页面，按层级深度优先排序。
        
        Args:
            query: 搜索查询字符串
            limit: 最大结果数量
            
        Returns:
            搜索结果列表，按相关性和层级排序
        """
        if not self._initialized:
            await self.initialize()
            
        try:
            async with self._driver.session() as session:
                # 构建搜索查询，优先考虑层级深度
                search_query = """
                MATCH (p:NotionPage)
                WHERE toLower(p.title) CONTAINS toLower($query)
                   OR any(tag IN p.tags WHERE toLower(tag) CONTAINS toLower($query))
                RETURN p.notionId as notionId, p.title as title, p.url as url, 
                       p.tags as tags, p.level as level, p.lastEditedTime as lastEditedTime
                ORDER BY 
                    CASE WHEN toLower(p.title) = toLower($query) THEN 5
                         WHEN toLower(p.title) CONTAINS toLower($query) THEN 4
                         WHEN any(tag IN p.tags WHERE toLower(tag) = toLower($query)) THEN 3
                         WHEN any(tag IN p.tags WHERE toLower(tag) CONTAINS toLower($query)) THEN 2
                         ELSE 1 END DESC,
                    p.level DESC,  // 优先深层级页面
                    p.lastEditedTime DESC
                LIMIT $limit
                """
                
                result = await session.run(search_query, query=query, limit=limit)
                
                search_results = []
                async for record in result:
                    # 计算相关性评分
                    title = record["title"]
                    tags = record["tags"] or []
                    level = record["level"] or 0
                    
                    relevance = self._calculate_relevance_score(query, title, tags, level)
                    
                    search_results.append(SearchResult(
                        notion_id=record["notionId"],
                        title=title,
                        url=record["url"],
                        relevance_score=relevance,
                        tags=tags,
                        relationship_context=f"Level {level} page, text match"
                    ))
                
                return search_results
            
        except Exception as e:
            logger.error(f"Error performing search: {e}")
            return []
    
    def _calculate_relevance_score(self, query: str, title: str, tags: List[str], level: int) -> float:
        """计算相关性评分，考虑标题匹配、标签匹配和层级深度"""
        score = 0.0
        query_lower = query.lower()
        title_lower = title.lower()
        
        # 标题匹配评分
        if query_lower == title_lower:
            score += 1.0
        elif query_lower in title_lower:
            score += 0.8
        elif title_lower in query_lower:
            score += 0.6
        
        # 标签匹配评分
        for tag in tags:
            tag_lower = tag.lower()
            if query_lower == tag_lower:
                score += 0.5
            elif query_lower in tag_lower or tag_lower in query_lower:
                score += 0.3
        
        # 层级深度奖励（深层页面通常包含更具体的信息）
        level_bonus = min(level * 0.1, 0.3)  # 最多0.3的层级奖励
        score += level_bonus
        
        return min(score, 1.0)  # 限制在1.0以内
    
    async def expand_from_pages(self, page_ids: List[str], depth: int = 1, 
                              relation_types: Optional[List[RelationType]] = None) -> List[ExpandResult]:
        """
        从给定页面扩展查找相关页面，优先选择深层级页面。
        
        Args:
            page_ids: 起始页面ID列表
            depth: 最大遍历深度
            relation_types: 要遵循的关系类型
            
        Returns:
            扩展结果列表
        """
        if not self._initialized:
            await self.initialize()
            
        try:
            async with self._driver.session() as session:
                # 构建关系类型过滤器
                relation_filter = ""
                if relation_types:
                    relation_types_str = "|".join([rt.value for rt in relation_types])
                    relation_filter = f":{relation_types_str}"
                
                # 查询，优先返回深层级页面
                query = f"""
                MATCH path = (start:NotionPage)-[*1..{depth}]->(related:NotionPage)
                WHERE start.notionId IN $page_ids
                AND related.notionId <> start.notionId
                RETURN DISTINCT 
                    related.notionId as notionId,
                    related.title as title,
                    related.url as url,
                    related.tags as tags,
                    related.level as level,
                    length(path) as depth,
                    [r in relationships(path) | type(r)] as pathTypes
                ORDER BY related.level DESC, length(path) ASC
                LIMIT 50
                """
                
                result = await session.run(query, page_ids=page_ids)
                
                expand_results = []
                async for record in result:
                    expand_results.append(ExpandResult(
                        page_id=record["notionId"],
                        title=record["title"],
                        url=record["url"],
                        depth=record["depth"],
                        path=record["pathTypes"],
                        tags=record["tags"] or []
                    ))
                
                return expand_results
            
        except Exception as e:
            logger.error(f"Error expanding from pages: {e}")
            return []
    
    async def get_deepest_level_pages(self, limit: int = 10) -> List[SearchResult]:
        """
        获取层级最深的页面（通常包含最具体的信息）。
        
        Args:
            limit: 最大结果数量
            
        Returns:
            按层级深度排序的页面列表
        """
        if not self._initialized:
            await self.initialize()
            
        try:
            async with self._driver.session() as session:
                query = """
                MATCH (p:NotionPage)
                WHERE p.level IS NOT NULL
                RETURN p.notionId as notionId, p.title as title, p.url as url, 
                       p.tags as tags, p.level as level
                ORDER BY p.level DESC, p.lastEditedTime DESC
                LIMIT $limit
                """
                
                result = await session.run(query, limit=limit)
                
                search_results = []
                async for record in result:
                    level = record["level"] or 0
                    search_results.append(SearchResult(
                        notion_id=record["notionId"],
                        title=record["title"],
                        url=record["url"],
                        relevance_score=1.0,  # 深层页面默认高相关性
                        tags=record["tags"] or [],
                        relationship_context=f"Deepest level page (Level {level})"
                    ))
                
                return search_results
            
        except Exception as e:
            logger.error(f"Error getting deepest level pages: {e}")
            return []
    
    async def get_graph_stats(self) -> GraphStats:
        """Get statistics about the graph."""
        if not self._initialized:
            await self.initialize()
            
        try:
            async with self._driver.session() as session:
                # Count total pages
                page_result = await session.run("MATCH (p:NotionPage) RETURN count(p) as total_pages")
                page_record = await page_result.single()
                total_pages = page_record["total_pages"] if page_record else 0
                
                # Count total relationships
                rel_result = await session.run("MATCH ()-[r]->() RETURN count(r) as total_relationships")
                rel_record = await rel_result.single()
                total_relationships = rel_record["total_relationships"] if rel_record else 0
                
                # Count relationships by type
                rel_type_result = await session.run("MATCH ()-[r]->() RETURN type(r) as rel_type, count(r) as count")
                relationship_counts = {}
                async for record in rel_type_result:
                    relationship_counts[record["rel_type"]] = record["count"]
                
                # Get most connected pages
                connected_result = await session.run("""
                    MATCH (p:NotionPage)-[r]-(otherPage:NotionPage)
                    RETURN p.notionId as notionId, p.title as title, p.level as level,
                           count(r) as connection_count
                    ORDER BY connection_count DESC, p.level DESC
                    LIMIT 10
                """)
                
                most_connected = []
                async for record in connected_result:
                    most_connected.append({
                        "notion_id": record["notionId"], 
                        "title": record["title"], 
                        "level": record["level"],
                        "connections": record["connection_count"]
                    })
                
                return GraphStats(
                    total_pages=total_pages,
                    total_relationships=total_relationships,
                    relationship_counts=relationship_counts,
                    most_connected_pages=most_connected,
                    last_sync=datetime.now()
                )
            
        except Exception as e:
            logger.error(f"Error getting graph stats: {e}")
            return GraphStats(
                total_pages=0,
                total_relationships=0,
                relationship_counts={},
                most_connected_pages=[],
                last_sync=datetime.now()
            )
    
    async def health_check(self) -> bool:
        """Check if the graph database is accessible."""
        try:
            if not self._initialized:
                await self.initialize()
            
            async with self._driver.session() as session:
                result = await session.run("RETURN 1 as test")
                record = await result.single()
                return record["test"] == 1
            
        except Exception as e:
            logger.error(f"Graph database health check failed: {e}")
            return False
    
    async def delete_page(self, notion_id: str) -> bool:
        """Delete a page and all its relationships."""
        if not self._initialized:
            await self.initialize()
            
        try:
            async with self._driver.session() as session:
                query = """
                MATCH (p:NotionPage {notionId: $notion_id})
                DETACH DELETE p
                """
                
                await session.run(query, notion_id=notion_id)
                logger.debug(f"Deleted page {notion_id}")
                return True
            
        except Exception as e:
            logger.error(f"Error deleting page {notion_id}: {e}")
            return False
    
    async def clear_all_data(self) -> bool:
        """Clear all data from the graph (use with caution)."""
        if not self._initialized:
            await self.initialize()
            
        try:
            async with self._driver.session() as session:
                # Delete all NotionPage nodes and relationships
                await session.run("MATCH (p:NotionPage) DETACH DELETE p")
                
                # Delete all Tag nodes
                await session.run("MATCH (t:Tag) DETACH DELETE t")
                
                logger.info("Cleared all data from the graph")
                return True
            
        except Exception as e:
            logger.error(f"Error clearing graph data: {e}")
            return False
    
    # 标准接口方法（为了兼容意图搜索系统）
    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        标准搜索接口，返回字典格式的结果
        
        Args:
            query: 搜索查询
            limit: 结果限制
            
        Returns:
            搜索结果字典列表
        """
        search_results = await self.search_by_query(query, limit)
        
        # 转换为字典格式
        return [
            {
                'node_id': result.notion_id,
                'name': result.title,
                'labels': result.tags,
                'score': result.relevance_score,
                'url': result.url,
                'context': result.relationship_context
            }
            for result in search_results
        ]
    
    async def expand(self, page_ids: List[str], depth: int = 1) -> List[Dict[str, Any]]:
        """
        标准扩展接口，返回字典格式的结果
        
        Args:
            page_ids: 起始页面ID列表
            depth: 扩展深度
            
        Returns:
            扩展结果字典列表
        """
        expand_results = await self.expand_from_pages(page_ids, depth)
        
        # 转换为字典格式
        return [
            {
                'page_id': result.page_id,
                'title': result.title,
                'url': result.url,
                'depth': result.depth,
                'path': result.path,
                'tags': result.tags
            }
            for result in expand_results
        ]