#!/usr/bin/env python3
"""
测试embedding搜索功能的脚本
"""
import asyncio
import json
from typing import List
from core.graphiti_client import GraphitiClient
from core.embedding_service import GoogleEmbeddingService

async def test_embedding_search():
    """测试embedding搜索的完整流程"""
    print("=== 开始测试 Embedding 搜索功能 ===\n")

    # 初始化客户端
    graphiti_client = GraphitiClient()
    embedding_service = GoogleEmbeddingService()

    try:
        # 1. 测试不同的查询词
        test_queries = [
            "项目管理",
            "技术架构",
            "用户体验",
            "数据分析",
            "系统设计"
        ]

        print("1. 测试查询词embedding生成:")
        query_embeddings = {}
        for query in test_queries:
            embedding = await embedding_service.get_embedding(query)
            query_embeddings[query] = embedding
            print(f"   {query}: 维度={len(embedding)}, 前3个值={embedding[:3]}")

        print("\n2. 检查数据库中的embedding数据:")
        # 使用neo4j driver直接查询
        async with graphiti_client.driver.session() as session:
            # 检查有embedding的页面数量
            result = await session.run("""
                MATCH (n:NotionPage)
                WHERE n.embedding IS NOT NULL
                RETURN count(n) as total_count
            """)
            record = await result.single()
            total_count = record["total_count"]
            print(f"   数据库中有embedding的页面总数: {total_count}")

            # 检查几个具体页面的embedding
            result = await session.run("""
                MATCH (n:NotionPage)
                WHERE n.embedding IS NOT NULL
                RETURN n.notionId, n.title, size(n.embedding) as embedding_size,
                       n.embedding[0..3] as first_few_values
                LIMIT 5
            """)
            print(f"   前5个页面的embedding信息:")
            records = await result.data()
            for record in records:
                title = record["title"][:40] + "..." if len(record["title"]) > 40 else record["title"]
                print(f"     - {title}: 维度={record['embedding_size']}, 前3个值={record['first_few_values']}")

        print("\n3. 检查向量索引状态:")
        async with graphiti_client.driver.session() as session:
            try:
                result = await session.run("SHOW INDEXES YIELD name, type, state WHERE type = 'VECTOR'")
                records = await result.data()
                if records:
                    for record in records:
                        print(f"   索引: {record['name']}, 状态: {record['state']}")
                else:
                    print("   未找到向量索引")
            except Exception as e:
                print(f"   查询索引状态出错: {e}")

        print("\n4. 测试向量搜索:")
        for query in test_queries[:2]:  # 只测试前2个查询
            print(f"\n   测试查询: '{query}'")
            try:
                # 使用GraphitiClient的搜索方法
                results = await graphiti_client.search_similar_pages(
                    query_embedding=query_embeddings[query],
                    limit=3,
                    similarity_threshold=0.7
                )

                if results:
                    print(f"     找到 {len(results)} 个相关结果:")
                    for i, result in enumerate(results):
                        # 直接访问字典的键
                        notion_id = result.get('notionId', 'N/A')
                        title = result.get('title', 'N/A')
                        score = result.get('score', 'N/A')
                        print(f"       {i+1}. {title[:50]}... (ID: {notion_id[:8]}..., 分数: {score})")
                else:
                    print("     未找到相关结果")

            except Exception as e:
                print(f"     搜索出错: {e}")
                import traceback
                traceback.print_exc()

        print("\n5. 检查是否所有embedding都相同:")
        async with graphiti_client.driver.session() as session:
            result = await session.run("""
                MATCH (n:NotionPage)
                WHERE n.embedding IS NOT NULL
                WITH DISTINCT n.embedding as unique_embedding
                RETURN count(unique_embedding) as unique_count
            """)
            record = await result.single()
            unique_count = record["unique_count"]
            print(f"   数据库中唯一embedding向量数量: {unique_count}")

            if unique_count == 1:
                print("   ⚠️  警告: 所有页面的embedding向量都相同！这是问题所在！")
            elif unique_count < total_count:
                print(f"   ⚠️  警告: 有重复的embedding向量，唯一数({unique_count}) < 总数({total_count})")
            else:
                print("   ✅ embedding向量都是唯一的")

    except Exception as e:
        print(f"测试过程中出错: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await graphiti_client.close()

    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    asyncio.run(test_embedding_search())