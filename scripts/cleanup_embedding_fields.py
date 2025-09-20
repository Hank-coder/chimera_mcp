#!/usr/bin/env python3
"""
清理Neo4j数据库中的冗余embedding字段
保留：geminiEmbedding, geminiEmbeddingText, geminiEmbeddingUpdatedAt
删除：titleEmbedding, embeddingText, embeddingUpdatedAt, updatedAt
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.graphiti_client import GraphitiClient
from config.logging import setup_logging
from loguru import logger


class EmbeddingFieldCleaner:
    """清理embedding字段的工具类"""

    def __init__(self):
        self.graphiti_client = GraphitiClient()

    async def initialize(self):
        """初始化客户端"""
        await self.graphiti_client.initialize()

    async def close(self):
        """关闭客户端"""
        await self.graphiti_client.close()

    async def check_current_fields(self):
        """检查当前所有页面的字段情况"""
        logger.info("🔍 检查当前数据库字段情况...")

        async with self.graphiti_client._driver.session() as session:
            # 检查字段统计
            result = await session.run("""
                MATCH (n:NotionPage)
                RETURN
                    count(n) as total_pages,
                    count(n.geminiEmbedding) as has_gemini_embedding,
                    count(n.titleEmbedding) as has_title_embedding,
                    count(n.geminiEmbeddingText) as has_gemini_text,
                    count(n.embeddingText) as has_old_text,
                    count(n.geminiEmbeddingUpdatedAt) as has_gemini_time,
                    count(n.embeddingUpdatedAt) as has_old_time,
                    count(n.updatedAt) as has_updated_at
            """)

            record = await result.single()

            logger.info("📊 字段统计:")
            logger.info(f"  总页面数: {record['total_pages']}")
            logger.info(f"  有geminiEmbedding: {record['has_gemini_embedding']}")
            logger.info(f"  有titleEmbedding (冗余): {record['has_title_embedding']}")
            logger.info(f"  有geminiEmbeddingText: {record['has_gemini_text']}")
            logger.info(f"  有embeddingText (冗余): {record['has_old_text']}")
            logger.info(f"  有geminiEmbeddingUpdatedAt: {record['has_gemini_time']}")
            logger.info(f"  有embeddingUpdatedAt (冗余): {record['has_old_time']}")
            logger.info(f"  有updatedAt (冗余): {record['has_updated_at']}")

            return record

    async def cleanup_redundant_fields(self, dry_run=True):
        """清理冗余字段"""
        logger.info(f"🧹 {'预览模式' if dry_run else '执行模式'}: 清理冗余embedding字段...")

        # 要删除的冗余字段
        redundant_fields = [
            'titleEmbedding',
            'embeddingText',
            'embeddingUpdatedAt',
            'updatedAt'
        ]

        async with self.graphiti_client._driver.session() as session:
            for field in redundant_fields:
                if dry_run:
                    # 预览模式：只查询有这个字段的页面数量
                    result = await session.run(f"""
                        MATCH (n:NotionPage)
                        WHERE n.{field} IS NOT NULL
                        RETURN count(n) as count
                    """)

                    record = await result.single()
                    count = record['count']

                    if count > 0:
                        logger.info(f"  🔍 {field}: {count} 个页面需要清理")
                    else:
                        logger.info(f"  ✅ {field}: 已经清理完成")

                else:
                    # 执行模式：实际删除字段
                    result = await session.run(f"""
                        MATCH (n:NotionPage)
                        WHERE n.{field} IS NOT NULL
                        REMOVE n.{field}
                        RETURN count(n) as cleaned_count
                    """)

                    record = await result.single()
                    cleaned_count = record['cleaned_count']

                    if cleaned_count > 0:
                        logger.info(f"  ✅ {field}: 清理了 {cleaned_count} 个页面")
                    else:
                        logger.info(f"  ⏭️ {field}: 无需清理")

    async def verify_gemini_fields(self):
        """验证Gemini字段的完整性"""
        logger.info("🔍 验证Gemini embedding字段完整性...")

        async with self.graphiti_client._driver.session() as session:
            result = await session.run("""
                MATCH (n:NotionPage)
                WHERE n.geminiEmbedding IS NOT NULL
                RETURN
                    count(n) as pages_with_embedding,
                    count(n.geminiEmbeddingText) as pages_with_text,
                    count(n.geminiEmbeddingUpdatedAt) as pages_with_timestamp,
                    avg(size(n.geminiEmbedding)) as avg_embedding_dimension
            """)

            record = await result.single()

            logger.info("📊 Gemini字段验证:")
            logger.info(f"  有embedding向量: {record['pages_with_embedding']}")
            logger.info(f"  有embedding文本: {record['pages_with_text']}")
            logger.info(f"  有时间戳: {record['pages_with_timestamp']}")
            logger.info(f"  平均向量维度: {record['avg_embedding_dimension']:.0f}")

            # 检查是否有维度不正确的向量
            result = await session.run("""
                MATCH (n:NotionPage)
                WHERE n.geminiEmbedding IS NOT NULL
                AND size(n.geminiEmbedding) <> 3072
                RETURN count(n) as invalid_dimension_count
            """)

            record = await result.single()
            invalid_count = record['invalid_dimension_count']

            if invalid_count > 0:
                logger.warning(f"  ⚠️ 有 {invalid_count} 个页面的向量维度不是3072")
            else:
                logger.info(f"  ✅ 所有向量维度都正确 (3072维)")

async def main():
    """主函数"""
    setup_logging()

    import argparse
    parser = argparse.ArgumentParser(description="清理Neo4j中的冗余embedding字段")
    parser.add_argument("--execute", action="store_true",
                       help="执行清理（默认为预览模式）")
    parser.add_argument("--check-only", action="store_true",
                       help="只检查字段状态，不执行清理")

    args = parser.parse_args()

    cleaner = EmbeddingFieldCleaner()

    try:
        await cleaner.initialize()

        # 检查当前状态
        await cleaner.check_current_fields()

        if not args.check_only:
            print()
            # 清理冗余字段
            await cleaner.cleanup_redundant_fields(dry_run=not args.execute)

            print()
            # 验证Gemini字段
            await cleaner.verify_gemini_fields()

            if not args.execute:
                logger.info("\n💡 使用 --execute 参数执行实际清理")

    except Exception as e:
        logger.error(f"清理过程出错: {e}")
        raise
    finally:
        await cleaner.close()

if __name__ == "__main__":
    asyncio.run(main())