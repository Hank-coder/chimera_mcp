#!/usr/bin/env python3
"""
批量生成embedding脚本
为Neo4j中所有embedding为空的页面生成embedding
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.logging import setup_logging
from core.embedding_service import generate_page_embedding, get_embedding_stats, get_pages_without_embedding
from core.embedding_search import EmbeddingSearchService
from loguru import logger


class BatchEmbeddingGenerator:
    """批量embedding生成器"""

    def __init__(self):
        self.embedding_search_service = EmbeddingSearchService()
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.total_count = 0

    async def initialize(self):
        """初始化客户端"""
        await self.embedding_search_service.initialize()

    async def close(self):
        """关闭客户端"""
        await self.embedding_search_service.close()

    async def get_pages_without_embedding(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取没有embedding的页面列表"""
        return await get_pages_without_embedding(limit)

    async def generate_embedding_for_page(self, page_info: Dict[str, Any]) -> bool:
        """为单个页面生成embedding"""

        page_id = page_info['notion_id']
        page_title = page_info['title']

        try:
            logger.info(f"开始为页面生成embedding: {page_title} ({page_id})")

            # 生成新的Gemini embedding
            embedding_vector, embedding_text = await generate_page_embedding(page_id)

            if not embedding_vector:
                logger.warning(f"页面 {page_title} embedding生成失败")
                return False

            # 更新到EmbeddingSearchService（新的3072维Gemini embedding）
            success = await self.embedding_search_service.update_page_embedding(
                notion_id=page_id,
                embedding_text=embedding_text,
                embedding_vector=embedding_vector
            )

            if success:
                logger.info(f"✅ 页面 {page_title} embedding更新成功")
                return True
            else:
                logger.error(f"❌ 页面 {page_title} embedding更新失败")
                return False

        except Exception as e:
            logger.error(f"❌ 处理页面 {page_title} 时出错: {e}")
            return False

    async def batch_generate(self, batch_size: int = 10, max_pages: int = 100):
        """批量生成embedding"""

        logger.info(f"🚀 开始批量生成embedding (批量大小: {batch_size}, 最大页面数: {max_pages})")

        # 获取需要处理的页面
        pages_without_embedding = await self.get_pages_without_embedding(max_pages)
        self.total_count = len(pages_without_embedding)

        if not pages_without_embedding:
            logger.info("🎉 所有页面都已有embedding，无需处理")
            return

        logger.info(f"📊 找到 {self.total_count} 个需要生成embedding的页面")

        start_time = time.time()

        # 分批处理
        for i in range(0, self.total_count, batch_size):
            batch = pages_without_embedding[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (self.total_count + batch_size - 1) // batch_size

            logger.info(f"📦 处理批次 {batch_num}/{total_batches} ({len(batch)} 个页面)")

            # 处理当前批次
            for page_info in batch:
                success = await self.generate_embedding_for_page(page_info)

                if success:
                    self.success_count += 1
                else:
                    self.failed_count += 1

                # 避免API限制，稍微延迟
                await asyncio.sleep(0.5)

            # 批次间稍长延迟
            if i + batch_size < self.total_count:
                logger.info(f"⏳ 批次完成，等待2秒后继续...")
                await asyncio.sleep(2)

        elapsed_time = time.time() - start_time

        # 输出统计信息
        self.print_summary(elapsed_time)

    def print_summary(self, elapsed_time: float):
        """打印处理摘要"""

        logger.info("=" * 60)
        logger.info("📊 批量embedding生成完成")
        logger.info("=" * 60)
        logger.info(f"总页面数: {self.total_count}")
        logger.info(f"✅ 成功: {self.success_count}")
        logger.info(f"❌ 失败: {self.failed_count}")
        logger.info(f"⏭️ 跳过: {self.skipped_count}")
        logger.info(f"⏱️ 总耗时: {elapsed_time:.1f} 秒")
        logger.info(f"📈 平均速度: {elapsed_time / max(1, self.total_count):.1f} 秒/页面")

        success_rate = (self.success_count / max(1, self.total_count)) * 100
        logger.info(f"🎯 成功率: {success_rate:.1f}%")

        if self.success_count > 0:
            logger.info("🎉 批量embedding生成成功完成！")
        elif self.failed_count > 0:
            logger.warning("⚠️ 部分页面embedding生成失败，请检查日志")
        else:
            logger.info("ℹ️ 无页面需要处理")


async def check_embedding_stats():
    """检查embedding统计信息"""

    logger.info("📊 检查embedding统计信息...")

    try:
        # 获取embedding统计信息
        stats = await get_embedding_stats()

        logger.info("Gemini embedding状态 (3072维):")
        logger.info(f"  📄 总页面数: {stats['total_pages']}")
        logger.info(f"  ✅ 有embedding: {stats['pages_with_embedding']}")
        logger.info(f"  ❌ 无embedding: {stats['pages_without_embedding']}")
        logger.info(f"  📈 覆盖率: {stats['embedding_coverage_percentage']:.1f}%")

        return stats

    except Exception as e:
        logger.error(f"获取embedding统计失败: {e}")
        return {
            "total_pages": 0,
            "pages_with_embedding": 0,
            "pages_without_embedding": 0,
            "embedding_coverage_percentage": 0.0
        }


async def main():
    """主函数"""

    import argparse

    parser = argparse.ArgumentParser(
        description="批量为Neo4j中的页面生成embedding",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python scripts/batch_generate_embeddings.py                    # 检查统计信息
  python scripts/batch_generate_embeddings.py --generate         # 生成所有缺失的embedding
  python scripts/batch_generate_embeddings.py --generate --max-pages 50  # 限制最多处理50个页面
  python scripts/batch_generate_embeddings.py --generate --batch-size 5   # 设置批量大小为5
  python scripts/batch_generate_embeddings.py --stats            # 只显示统计信息
        """
    )

    parser.add_argument(

        "--generate",
        action="store_true",
        help="执行批量embedding生成"
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="只显示embedding统计信息"
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="最大处理页面数 (默认: 100)"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="批量处理大小 (默认: 10)"
    )

    args = parser.parse_args()

    # 设置日志
    setup_logging()

    # 显示标题
    logger.info("=" * 60)
    logger.info("🔧 批量Embedding生成工具")
    logger.info("=" * 60)

    try:
        # 检查统计信息
        stats = await check_embedding_stats()

        if args.stats:
            # 只显示统计信息
            return

        if not args.generate:
            # 默认显示统计信息和使用提示
            logger.info("\n💡 使用 --generate 参数开始批量生成embedding")
            logger.info("💡 使用 --help 查看所有选项")
            return

        if stats['pages_without_embedding'] == 0:
            logger.info("🎉 所有页面都已有embedding，无需处理")
            return

        # 执行批量生成
        generator = BatchEmbeddingGenerator()
        await generator.initialize()

        try:
            await generator.batch_generate(
                batch_size=args.batch_size,
                max_pages=args.max_pages
            )
        finally:
            await generator.close()

        # 最终统计
        logger.info("\n📊 生成完成后的统计信息:")
        await check_embedding_stats()

    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())