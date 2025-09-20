"""
新的Embedding搜索服务
专门适配Gemini-embedding-001模型（3072维）
不影响现有的graphiti_client.py
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
import numpy as np
from neo4j import AsyncGraphDatabase

from .models import NotionPageMetadata
from .embedding_service import GoogleEmbeddingService
from config.settings import settings


class EmbeddingSearchService:
    """
    新的Embedding搜索服务
    专门用于3072维的Gemini embedding搜索
    """

    def __init__(self):
        """初始化搜索服务"""
        self.neo4j_uri = settings.neo4j_uri
        self.neo4j_user = settings.neo4j_username
        self.neo4j_password = settings.neo4j_password
        self._driver = None
        self._embedding_service = GoogleEmbeddingService()

    async def initialize(self):
        """初始化Neo4j连接"""
        try:
            self._driver = AsyncGraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password)
            )

            # 创建新的embedding索引（如果不存在）
            await self._create_embedding_index()
            # logger.info("EmbeddingSearchService初始化完成")

        except Exception as e:
            logger.error(f"EmbeddingSearchService初始化失败: {e}")
            raise

    async def close(self):
        """关闭连接"""
        if self._driver:
            await self._driver.close()
            logger.info("EmbeddingSearchService连接已关闭")

    async def _create_embedding_index(self):
        """创建新的embedding向量索引"""
        async with self._driver.session() as session:
            try:
                # 创建3072维的向量索引
                await session.run("""
                    CREATE VECTOR INDEX gemini_embedding_index IF NOT EXISTS
                    FOR (n:NotionPage) ON (n.geminiEmbedding)
                    OPTIONS { indexConfig: {
                      `vector.dimensions`: 3072,
                      `vector.similarity_function`: 'cosine'
                    }}
                """)
                # logger.info("🔥 创建Gemini embedding向量索引成功 (3072维)")
            except Exception as e:
                logger.warning(f"⚠️ 向量索引创建失败，将使用手动计算: {e}")

    async def search_similar_pages(
        self,
        query_text: str,
        limit: int = 5,
        similarity_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        搜索语义相似的页面

        Args:
            query_text: 查询文本
            limit: 返回结果数量限制
            similarity_threshold: 相似度阈值

        Returns:
            相似页面列表
        """
        try:
            # 1. 生成查询embedding
            query_embedding = await self._embedding_service.get_embedding(query_text)
            if not query_embedding:
                logger.error("无法生成查询embedding")
                return []

            logger.debug(f"查询embedding生成成功，维度: {len(query_embedding)}")

            # 2. 尝试向量索引搜索
            results = await self._vector_search(query_embedding, limit, similarity_threshold)

            if not results:
                # 3. 回退到手动计算
                logger.info("向量索引搜索无结果，回退到手动余弦相似度计算")
                results = await self._manual_cosine_search(query_embedding, limit, similarity_threshold)

            # logger.info(f"Embedding搜索完成，找到 {len(results)} 个相关结果")
            return results

        except Exception as e:
            logger.error(f"Embedding搜索失败: {e}")
            return []

    async def _vector_search(
        self,
        query_embedding: List[float],
        limit: int,
        similarity_threshold: float
    ) -> List[Dict[str, Any]]:
        """使用Neo4j向量索引搜索"""
        try:
            async with self._driver.session() as session:
                result = await session.run("""
                    CALL db.index.vector.queryNodes(
                        'gemini_embedding_index',
                        $limit,
                        $query_embedding
                    ) YIELD node, score
                    WHERE score >= $threshold
                    AND NOT (node)<-[:CHILD_OF]-()
                    RETURN node.notionId as notionId,
                           node.title as title,
                           node.url as url,
                           score
                    ORDER BY score DESC
                """, {
                    "query_embedding": query_embedding,
                    "limit": limit,
                    "threshold": similarity_threshold
                })

                records = await result.data()

                if records:
                    logger.debug(f"🔥 向量索引搜索找到 {len(records)} 个结果")
                    return records
                else:
                    logger.debug("向量索引搜索无结果")
                    return []

        except Exception as e:
            logger.warning(f"向量索引搜索失败: {e}")
            return []

    async def _manual_cosine_search(
        self,
        query_embedding: List[float],
        limit: int,
        similarity_threshold: float
    ) -> List[Dict[str, Any]]:
        """手动余弦相似度计算"""
        try:
            async with self._driver.session() as session:
                # 获取所有有embedding的叶子节点页面（没有子页面的页面）
                result = await session.run("""
                    MATCH (n:NotionPage)
                    WHERE n.geminiEmbedding IS NOT NULL
                    AND NOT (n)<-[:CHILD_OF]-()
                    RETURN n.notionId as notionId,
                           n.title as title,
                           n.url as url,
                           n.geminiEmbedding as embedding
                """)

                records = await result.data()
                logger.debug(f"获取到 {len(records)} 个有embedding的页面")

                if not records:
                    return []

                # 计算余弦相似度
                similarities = []
                query_vec = np.array(query_embedding)
                query_norm = np.linalg.norm(query_vec)

                for record in records:
                    try:
                        page_embedding = record['embedding']
                        if not page_embedding or len(page_embedding) != len(query_embedding):
                            continue

                        page_vec = np.array(page_embedding)
                        page_norm = np.linalg.norm(page_vec)

                        if page_norm == 0 or query_norm == 0:
                            continue

                        # 余弦相似度
                        cosine_sim = np.dot(query_vec, page_vec) / (query_norm * page_norm)

                        if cosine_sim >= similarity_threshold:
                            similarities.append({
                                'notionId': record['notionId'],
                                'title': record['title'],
                                'url': record['url'],
                                'score': float(cosine_sim)
                            })

                    except Exception as e:
                        logger.warning(f"计算相似度时出错: {e}")
                        continue

                # 按相似度排序并限制数量
                similarities.sort(key=lambda x: x['score'], reverse=True)
                results = similarities[:limit]

                logger.debug(f"🔄 手动余弦相似度搜索找到 {len(results)} 个结果 (阈值 >= {similarity_threshold})")
                return results

        except Exception as e:
            logger.error(f"手动余弦相似度计算失败: {e}")
            return []

    async def update_page_embedding(self, notion_id: str, embedding_text: str, embedding_vector: List[float]) -> bool:
        """
        更新页面的embedding

        Args:
            notion_id: Notion页面ID
            embedding_text: 用于生成embedding的文本
            embedding_vector: embedding向量

        Returns:
            是否更新成功
        """
        try:
            async with self._driver.session() as session:
                await session.run("""
                    MATCH (n:NotionPage {notionId: $notion_id})
                    SET n.geminiEmbedding = $embedding_vector,
                        n.geminiEmbeddingText = $embedding_text,
                        n.geminiEmbeddingUpdatedAt = datetime()
                    RETURN n.notionId as updated_id
                """, {
                    "notion_id": notion_id,
                    "embedding_vector": embedding_vector,
                    "embedding_text": embedding_text
                })

                logger.debug(f"页面 {notion_id} 的Gemini embedding已更新")
                return True

        except Exception as e:
            logger.error(f"更新页面 {notion_id} embedding失败: {e}")
            return False

    async def batch_update_embeddings(self, updates: List[Dict[str, Any]]) -> int:
        """
        批量更新页面embeddings

        Args:
            updates: 更新列表，每个元素包含 {notion_id, embedding_text, embedding_vector}

        Returns:
            成功更新的数量
        """
        success_count = 0

        for update in updates:
            try:
                notion_id = update['notion_id']
                embedding_text = update['embedding_text']
                embedding_vector = update['embedding_vector']

                success = await self.update_page_embedding(notion_id, embedding_text, embedding_vector)
                if success:
                    success_count += 1

            except Exception as e:
                logger.error(f"批量更新embedding时出错: {e}")
                continue

        logger.info(f"批量embedding更新完成: {success_count}/{len(updates)} 成功")
        return success_count


# 便利函数
async def search_pages_by_text(query_text: str, limit: int = 5, similarity_threshold: float = 0.7) -> List[Dict[str, Any]]:
    """
    便利函数：根据文本搜索相似页面
    """
    search_service = EmbeddingSearchService()
    try:
        await search_service.initialize()
        results = await search_service.search_similar_pages(query_text, limit, similarity_threshold)
        return results
    finally:
        await search_service.close()


# 测试函数
async def test_embedding_search():
    """测试embedding搜索功能"""
    print("=== 测试Embedding搜索服务 ===\n")

    search_service = EmbeddingSearchService()
    try:
        await search_service.initialize()

        # 测试查询
        test_queries = [
            "项目管理",
            "技术架构",
            "用户体验"
        ]

        for query in test_queries:
            print(f"\n搜索: '{query}'")
            results = await search_service.search_similar_pages(query, limit=3, similarity_threshold=0.6)

            if results:
                print(f"找到 {len(results)} 个结果:")
                for i, result in enumerate(results):
                    print(f"  {i+1}. {result['title'][:50]}... (分数: {result['score']:.4f})")
            else:
                print("  未找到相关结果")

    finally:
        await search_service.close()


if __name__ == "__main__":
    asyncio.run(test_embedding_search())