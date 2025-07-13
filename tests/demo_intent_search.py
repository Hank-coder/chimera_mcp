#!/usr/bin/env python3
"""
意图搜索系统演示脚本

演示完整的工作流：
用户输入 → 意图识别 → Neo4j路径枚举 → Gemini选择 → 页面ID提取 → 内容返回
"""

import asyncio
from datetime import datetime
from agents.intent_search import search_user_intent
from core.notion_client import NotionClient


async def get_path_contents(path_titles, path_ids):
    """获取路径中所有页面的内容"""
    notion_client = NotionClient()
    path_contents = []
    
    for i, (title, page_id) in enumerate(zip(path_titles, path_ids)):
        try:
            content = await notion_client.get_page_content(page_id)
            path_contents.append({
                "position": i,
                "title": title,
                "notion_id": page_id,
                "content": content
            })
        except Exception as e:
            path_contents.append({
                "position": i,
                "title": title,
                "notion_id": page_id,
                "content": f"获取内容失败: {str(e)}"
            })
    
    return path_contents


async def demo_intent_search():
    """演示意图搜索功能 - 完整路径版：返回路径中所有NotionPage的ID和内容"""
    
    print("=" * 60)
    print("个人AI记忆核心 - 意图搜索系统演示（完整路径版）")
    print("=" * 60)
    
    # 测试查询列表
    test_queries = [
        "我想找关于机器学习的笔记",
        "Python编程相关的文档", 
        "数据分析的内容"
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'='*20} 测试查询 {i} {'='*20}")
        print(f"用户输入: {query}")
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # 执行意图搜索
            result = await search_user_intent(
                user_input=query,
                confidence_threshold=0.6,  # 降低阈值以获得更多结果
                max_results=1,  # 只返回1个最佳结果
                expansion_depth=1  # 最小扩展深度（Pydantic验证要求>=1）
            )
            
            # 输出搜索状态
            print(f"\n🔍 搜索状态:")
            print(f"  ✅ 成功: {result.success}")
            print(f"  📊 意图关键词: {result.intent_keywords}")
            
            if result.search_metadata:
                print(f"  ⏱️ 处理时间: {result.search_metadata.processing_time_ms:.2f}ms")
            
            # 提取最终结果
            if result.success and result.confidence_paths:
                best_path = result.confidence_paths[0]  # 取置信度最高的路径
                core_page = best_path.core_page
                
                print(f"\n📄 最佳匹配路径:")
                print(f"  🛤️ 完整路径: {core_page.path_string}")
                print(f"  💯 置信度: {core_page.confidence_score:.2f}")
                print(f"  📊 路径长度: {len(core_page.path_ids)} 个页面")
                
                # 获取路径中所有页面的内容
                if core_page.path_ids and core_page.path_titles:
                    print(f"\n📚 获取路径中所有页面内容...")
                    path_contents = await get_path_contents(core_page.path_titles, core_page.path_ids)
                    
                    print(f"\n🎯 完整路径内容:")
                    for page_content in path_contents:
                        print(f"\n  📄 [{page_content['position']}] {page_content['title']}")
                        print(f"    🆔 ID: {page_content['notion_id']}")
                        print(f"    📝 内容: {page_content['content'][:200]}...")
                    
                    # 最终返回结果：包含路径中所有页面
                    final_result = {
                        "path_string": core_page.path_string,
                        "confidence": core_page.confidence_score,
                        "path_contents": path_contents,
                        "total_pages": len(path_contents)
                    }
                    
                    print(f"\n✅ 最终返回结果:")
                    print(f"  🛤️ 路径: {final_result['path_string']}")
                    print(f"  💯 置信度: {final_result['confidence']:.2f}")
                    print(f"  📊 页面数量: {final_result['total_pages']}")
                    total_content_length = sum(len(p['content']) for p in path_contents)
                    print(f"  📝 总内容长度: {total_content_length} 字符")
                    
                else:
                    # 备用：如果没有路径信息，仍然显示核心页面
                    print(f"\n📄 核心页面（无路径信息）:")
                    print(f"  🆔 NotionPage ID: {core_page.notion_id}")
                    print(f"  📑 页面标题: {core_page.title}")
                    print(f"  📝 内容: {core_page.content[:300]}...")
                    
                    final_result = {
                        "notion_id": core_page.notion_id,
                        "title": core_page.title,
                        "content": core_page.content,
                        "confidence": core_page.confidence_score
                    }
                
            else:
                print(f"\n❌ 未找到匹配结果")
                if result.error:
                    print(f"  错误: {result.error}")
            
        except Exception as e:
            print(f"  ❌ 执行异常: {str(e)}")
        
        print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 等待一下再进行下一个查询
        if i < len(test_queries):
            print("\n⏳ 等待3秒后继续...")
            await asyncio.sleep(3)
    
    print(f"\n{'='*60}")
    print("演示完成！")
    print("="*60)


async def interactive_search():
    """交互式搜索模式 - 完整路径版：返回路径中所有NotionPage的ID和内容"""
    
    print("\n" + "="*50)
    print("🤖 交互式意图搜索（完整路径版）")
    print("输入 'quit' 或 'exit' 退出")
    print("="*50)
    
    while True:
        try:
            user_input = input("\n请输入您的查询: ").strip()
            
            if user_input.lower() in ['quit', 'exit', '退出']:
                print("👋 再见！")
                break
            
            if not user_input:
                print("⚠️ 请输入有效的查询内容")
                continue
            
            print(f"🔍 正在搜索: {user_input}")
            start_time = datetime.now()
            
            # 执行搜索
            result = await search_user_intent(
                user_input=user_input,
                confidence_threshold=0.5,
                max_results=1,  # 只返回最佳结果
                expansion_depth=1  # 最小扩展深度（Pydantic验证要求>=1）
            )
            
            end_time = datetime.now()
            processing_time = (end_time - start_time).total_seconds() * 1000
            
            # 显示结果
            print(f"\n📊 搜索完成 (耗时: {processing_time:.0f}ms)")
            
            if result.success and result.confidence_paths:
                # 获取最佳匹配
                best_path = result.confidence_paths[0]
                core_page = best_path.core_page
                
                print(f"\n🎯 最佳匹配路径:")
                print(f"🛤️ 完整路径: {core_page.path_string}")
                print(f"💯 置信度: {core_page.confidence_score:.2f}")
                print(f"📊 路径长度: {len(core_page.path_ids)} 个页面")
                
                # 获取路径中所有页面的内容
                if core_page.path_ids and core_page.path_titles:
                    print(f"\n📚 获取路径中所有页面内容...")
                    path_contents = await get_path_contents(core_page.path_titles, core_page.path_ids)
                    
                    print(f"\n📖 完整路径内容:")
                    for page_content in path_contents:
                        print(f"\n  📄 [{page_content['position']}] {page_content['title']}")
                        print(f"    🆔 ID: {page_content['notion_id']}")
                        print(f"    📝 内容: {page_content['content'][:300]}...")  # 显示前300字符
                    
                    # 最终结果
                    final_result = {
                        "path_string": core_page.path_string,
                        "confidence": core_page.confidence_score,
                        "path_contents": path_contents,
                        "total_pages": len(path_contents)
                    }
                    
                    total_content_length = sum(len(p['content']) for p in path_contents)
                    print(f"\n✅ 返回结果: 路径={final_result['path_string']}, {final_result['total_pages']}个页面, 总内容长度={total_content_length}字符")
                
                else:
                    # 备用：如果没有路径信息
                    print(f"\n📄 核心页面: {core_page.title}")
                    print(f"🆔 ID: {core_page.notion_id}")
                    print(f"📝 内容: {core_page.content[:300]}...")
                    
                    final_result = {
                        "notion_id": core_page.notion_id,
                        "title": core_page.title,
                        "content": core_page.content,
                        "confidence": core_page.confidence_score
                    }
                    
                    print(f"\n✅ 返回结果: ID={final_result['notion_id']}, 内容长度={len(final_result['content'])}字符")
                
            else:
                print("😔 未找到相关结果")
                if result.error:
                    print(f"错误: {result.error}")
        
        except KeyboardInterrupt:
            print("\n\n👋 用户中断，再见！")
            break
        except Exception as e:
            print(f"❌ 搜索出错: {str(e)}")


def print_usage():
    """打印使用说明"""
    print("""
🚀 意图搜索系统使用说明（完整路径版）

该系统实现了完整路径的个人知识库意图搜索工作流:

1️⃣ 意图识别: 从用户输入中提取关键词
2️⃣ 路径枚举: 在Neo4j图谱中搜索候选路径  
3️⃣ 智能选择: 使用Gemini评估路径置信度
4️⃣ 完整路径: 返回置信度最高的完整路径（如 "Hank -> 简历"）
5️⃣ 内容获取: 从Notion实时获取路径中所有页面的完整内容

核心特点:
✅ 完整路径输出：返回路径中所有NotionPage的ID和内容
✅ 路径关系保留：维持页面间的层级关系（父->子页面）
✅ 使用Pydantic模型进行类型安全的数据交换
✅ LangChain PromptTemplate管理所有prompt
✅ Gemini 2.0 Flash进行智能路径选择
✅ 并行获取多个页面的最新内容
✅ 完整的错误处理和降级机制

返回结果格式:
{
    "path_string": "Hank -> 简历",
    "confidence": 0.85,
    "path_contents": [
        {
            "position": 0,
            "title": "Hank",
            "notion_id": "页面ID1",
            "content": "Hank页面的完整内容..."
        },
        {
            "position": 1, 
            "title": "简历",
            "notion_id": "页面ID2",
            "content": "简历页面的完整内容..."
        }
    ],
    "total_pages": 2
}

使用方法:
python demo_intent_search.py demo    # 运行演示
python demo_intent_search.py interactive  # 交互模式
""")


async def main():
    """主函数"""
    import sys
    
    if len(sys.argv) < 2:
        print_usage()
        return
    
    mode = sys.argv[1].lower()
    
    if mode == 'demo':
        await demo_intent_search()
    elif mode == 'interactive':
        await interactive_search()
    elif mode == 'help':
        print_usage()
    else:
        print("❌ 无效的模式。支持的模式: demo, interactive, help")
        print_usage()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 程序被用户中断")
    except Exception as e:
        print(f"❌ 程序异常: {str(e)}")
        import traceback
        traceback.print_exc()