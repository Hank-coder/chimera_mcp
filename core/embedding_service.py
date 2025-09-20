"""
Embedding服务模块
负责从Notion页面提取结构化标题信息，生成embedding向量
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import json
from loguru import logger
from google import genai
from google.genai import types

from .models import NotionPageMetadata
from .notion_client import NotionExtractor
from config.settings import settings


class GoogleEmbeddingService:
    """Google Embedding服务封装"""

    def __init__(self):
        """初始化Google Embedding服务"""
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        # logger.info("Google Embedding服务初始化完成")

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """
        获取文本的embedding向量

        Args:
            text: 要embedding的文本

        Returns:
            embedding向量，失败时返回None
        """
        try:
            # 使用Google的embedding模型 - 根据官方文档的正确方式
            result = self.client.models.embed_content(
                model="gemini-embedding-001",  # 使用官方推荐的模型名称
                contents=text,
                config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY")
            )

            # 根据官方文档，结果在embeddings字段中，第一个元素是我们的结果
            embedding_vector = result.embeddings[0].values
            logger.debug(f"成功生成embedding，向量维度: {len(embedding_vector)}")
            return embedding_vector

        except Exception as e:
            logger.error(f"Google embedding API调用失败: {e}")
            return None


async def extract_structured_headings(page_id: str) -> Optional[Dict[str, Any]]:
    """
    按文章顺序提取结构化标题信息

    Args:
        page_id: Notion页面ID

    Returns:
        结构化标题信息，包含page_title和sections
    """
    try:
        notion_client = NotionExtractor(settings.notion_token)

        # 1. 获取页面基本信息
        page_info = await notion_client.get_page_basic_info(page_id)
        if not page_info:
            logger.warning(f"无法获取页面元数据: {page_id}")
            return None

        # 2. 获取页面内容块，保持顺序
        # 使用client.blocks.children.list获取页面块
        from notion_client.helpers import async_collect_paginated_api
        blocks_response = await async_collect_paginated_api(
            notion_client.client.blocks.children.list,
            block_id=page_id
        )
        blocks = blocks_response
        if not blocks:
            logger.debug(f"页面 {page_id} 没有内容块，使用标题信息")
            blocks = []

        structured_content = {
            "page_title": page_info.get("title", "无标题"),
            "sections": []  # 按顺序存储章节
        }

        current_h1 = None
        current_h1_h2s = []
        standalone_h2s = []  # 🆕 收集独立的H2标题（没有H1父标题）

        for block in blocks:
            block_type = block.get("type")

            if block_type == "heading_1":
                # 保存前一个H1及其H2s
                if current_h1:
                    structured_content["sections"].append({
                        "h1_title": current_h1,
                        "h2_titles": current_h1_h2s.copy()
                    })

                # 开始新的H1
                try:
                    h1_text = ""
                    if block.get("heading_1") and block["heading_1"].get("rich_text"):
                        rich_text_list = block["heading_1"]["rich_text"]
                        if rich_text_list and len(rich_text_list) > 0:
                            h1_text = rich_text_list[0].get("plain_text", "")

                    current_h1 = h1_text or "未命名章节"
                    current_h1_h2s = []

                except Exception as e:
                    logger.warning(f"解析H1标题时出错: {e}")
                    current_h1 = "解析错误的章节"
                    current_h1_h2s = []

            elif block_type == "heading_2":
                # 解析H2标题
                try:
                    h2_text = ""
                    if block.get("heading_2") and block["heading_2"].get("rich_text"):
                        rich_text_list = block["heading_2"]["rich_text"]
                        if rich_text_list and len(rich_text_list) > 0:
                            h2_text = rich_text_list[0].get("plain_text", "")

                    if h2_text:
                        if current_h1:
                            # 有当前H1，将H2添加到H1下
                            current_h1_h2s.append(h2_text)
                        else:
                            # 🆕 没有H1，这是独立的H2标题
                            standalone_h2s.append(h2_text)

                except Exception as e:
                    logger.warning(f"解析H2标题时出错: {e}")

        # 保存最后一个H1及其H2s
        if current_h1:
            structured_content["sections"].append({
                "h1_title": current_h1,
                "h2_titles": current_h1_h2s.copy()
            })

        # 🆕 如果有独立的H2标题，创建一个特殊的section
        if standalone_h2s:
            structured_content["sections"].append({
                "h1_title": "",  # 空的H1标题表示这些是独立的H2
                "h2_titles": standalone_h2s.copy()
            })

        logger.debug(f"页面 {page_id} 结构化标题提取完成: 标题={structured_content['page_title']}, 章节数={len(structured_content['sections'])}")
        return structured_content

    except Exception as e:
        logger.error(f"提取页面 {page_id} 结构化标题时出错: {e}")
        return None


def format_structured_text_for_embedding(structured_content: Dict[str, Any]) -> str:
    """
    将结构化内容格式化为embedding文本
    专为RAG优化，去除无用的格式词

    Args:
        structured_content: extract_structured_headings返回的结构化内容

    Returns:
        格式化后的文本，适合用于RAG embedding
    """
    if not structured_content:
        return ""

    parts = []

    # 1. 添加页面标题（无前缀）
    page_title = structured_content.get('page_title', '').strip()
    if page_title:
        parts.append(page_title)

    # 2. 按顺序添加章节内容
    sections = structured_content.get('sections', [])
    for section in sections:
        h1_title = section.get('h1_title', '').strip()
        h2_titles = section.get('h2_titles', [])

        if h1_title:
            # 有H1标题：添加H1标题（无前缀）
            parts.append(h1_title)

        # 添加H2标题（无前缀），无论是否有H1
        if h2_titles:
            for h2_title in h2_titles:
                h2_title = h2_title.strip()
                if h2_title:
                    parts.append(h2_title)

    # 3. 用空格连接所有内容，便于向量搜索
    formatted_text = " ".join(parts)
    logger.debug(f"格式化文本长度: {len(formatted_text)} 字符")

    return formatted_text


async def generate_page_embedding(page_id: str) -> Tuple[Optional[List[float]], Optional[str]]:
    """
    为页面生成embedding向量和文本

    Args:
        page_id: Notion页面ID

    Returns:
        (embedding向量, embedding文本) 的元组，失败时返回(None, None)
    """
    try:
        # 1. 提取结构化标题
        structured_content = await extract_structured_headings(page_id)
        if not structured_content:
            logger.warning(f"页面 {page_id} 无法提取结构化内容")
            return None, None

        # 2. 格式化为embedding文本
        embedding_text = format_structured_text_for_embedding(structured_content)
        if not embedding_text or len(embedding_text.strip()) == 0:
            logger.warning(f"页面 {page_id} 生成的embedding文本为空")
            return None, None

        # 3. 生成embedding
        embedding_service = GoogleEmbeddingService()
        embedding_vector = await embedding_service.get_embedding(embedding_text)

        if embedding_vector:
            logger.info(f"页面 {page_id} embedding生成成功，向量维度: {len(embedding_vector)}")
        else:
            logger.error(f"页面 {page_id} embedding生成失败")

        return embedding_vector, embedding_text

    except Exception as e:
        logger.error(f"为页面 {page_id} 生成embedding时出错: {e}")
        return None, None


async def batch_generate_embeddings(page_ids: List[str], max_concurrent: int = 3) -> Dict[str, Tuple[Optional[List[float]], Optional[str]]]:
    """
    批量生成embedding

    Args:
        page_ids: 页面ID列表
        max_concurrent: 最大并发数

    Returns:
        {page_id: (embedding_vector, embedding_text)} 的字典
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def generate_single(page_id: str) -> Tuple[str, Tuple[Optional[List[float]], Optional[str]]]:
        async with semaphore:
            embedding_result = await generate_page_embedding(page_id)
            return page_id, embedding_result

    # 创建并发任务
    tasks = [generate_single(page_id) for page_id in page_ids]

    # 等待所有任务完成
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 整理结果
    embedding_results = {}
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"批量生成embedding时出错: {result}")
            continue

        page_id, (embedding_vector, embedding_text) = result
        embedding_results[page_id] = (embedding_vector, embedding_text)

    logger.info(f"批量生成embedding完成: {len(embedding_results)}/{len(page_ids)} 成功")
    return embedding_results


# 便利函数
async def get_page_embedding_info(page_id: str) -> Dict[str, Any]:
    """
    获取页面的完整embedding信息（用于调试和验证）

    Args:
        page_id: Notion页面ID

    Returns:
        包含原始内容、格式化文本、embedding向量等信息的字典
    """
    try:
        # 提取结构化内容
        structured_content = await extract_structured_headings(page_id)

        # 生成embedding
        embedding_vector, embedding_text = await generate_page_embedding(page_id)

        return {
            "page_id": page_id,
            "structured_content": structured_content,
            "embedding_text": embedding_text,
            "embedding_vector": embedding_vector,
            "embedding_dimension": len(embedding_vector) if embedding_vector else 0,
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"获取页面 {page_id} embedding信息时出错: {e}")
        return {
            "page_id": page_id,
            "error": str(e),
            "generated_at": datetime.now().isoformat()
        }


async def get_embedding_stats() -> Dict[str, Any]:
    """
    获取embedding统计信息

    Returns:
        包含总页面数、有embedding页面数等统计信息的字典
    """
    from core.embedding_search import EmbeddingSearchService

    embedding_search_service = EmbeddingSearchService()
    await embedding_search_service.initialize()

    try:
        async with embedding_search_service._driver.session() as session:
            result = await session.run("""
                MATCH (n:NotionPage)
                RETURN
                    count(n) as total_pages,
                    count(n.geminiEmbedding) as pages_with_embedding
            """)

            record = await result.single()
            total_pages = record['total_pages']
            pages_with_embedding = record['pages_with_embedding']
            pages_without_embedding = total_pages - pages_with_embedding
            embedding_coverage = (pages_with_embedding / max(1, total_pages)) * 100

            return {
                "total_pages": total_pages,
                "pages_with_embedding": pages_with_embedding,
                "pages_without_embedding": pages_without_embedding,
                "embedding_coverage_percentage": embedding_coverage
            }

    finally:
        await embedding_search_service.close()


async def get_pages_without_embedding(limit: int = 100) -> List[Dict[str, Any]]:
    """
    获取没有embedding的页面列表

    Args:
        limit: 返回的最大页面数

    Returns:
        没有embedding的页面列表
    """
    from core.embedding_search import EmbeddingSearchService

    embedding_search_service = EmbeddingSearchService()
    await embedding_search_service.initialize()

    try:
        async with embedding_search_service._driver.session() as session:
            result = await session.run("""
                MATCH (n:NotionPage)
                WHERE n.geminiEmbedding IS NULL
                AND NOT (n)<-[:CHILD_OF]-()
                RETURN n.notionId as notion_id, n.title as title
                LIMIT $limit
            """, {"limit": limit})

            records = await result.data()
            logger.debug(f"找到 {len(records)} 个没有embedding的页面")
            return records

    finally:
        await embedding_search_service.close()


# 示例使用
if __name__ == "__main__":
    async def test_embedding_service():
        """测试embedding服务"""

        # 测试页面ID（需要替换为实际的页面ID）
        test_page_id = "your-test-page-id"

        print("测试embedding服务...")

        # 1. 测试结构化标题提取
        print("\n1. 测试结构化标题提取:")
        structured_content = await extract_structured_headings(test_page_id)
        print(f"结构化内容: {json.dumps(structured_content, ensure_ascii=False, indent=2)}")

        # 2. 测试文本格式化
        print("\n2. 测试文本格式化:")
        formatted_text = format_structured_text_for_embedding(structured_content)
        print(f"格式化文本:\n{formatted_text}")

        # 3. 测试embedding生成
        print("\n3. 测试embedding生成:")
        embedding_vector, embedding_text = await generate_page_embedding(test_page_id)
        if embedding_vector:
            print(f"Embedding成功生成，维度: {len(embedding_vector)}")
            print(f"前5个维度值: {embedding_vector[:5]}")
        else:
            print("Embedding生成失败")

        # 4. 测试完整信息获取
        print("\n4. 测试完整信息获取:")
        full_info = await get_page_embedding_info(test_page_id)
        print(f"完整信息: {json.dumps(full_info, ensure_ascii=False, indent=2)}")

    # 运行测试
    asyncio.run(test_embedding_service())