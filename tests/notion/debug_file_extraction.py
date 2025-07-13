#!/usr/bin/env python3
"""
调试文档提取功能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.notion_client import NotionClient
from config.logging import setup_logging
from loguru import logger

async def debug_page_file_extraction(page_id: str):
    """调试指定页面的文档提取"""
    
    setup_logging()
    logger.info(f"🔍 开始调试页面: {page_id}")
    
    try:
        # 初始化客户端
        client = NotionClient()
        extractor = client.extractor
        
        # 1. 获取页面基本信息
        logger.info("📄 获取页面基本信息...")
        await extractor._rate_limit_wait()
        page_info = await extractor.client.pages.retrieve(page_id=page_id)
        logger.info(f"页面标题: {page_info.get('properties', {}).get('title', {})}")
        
        # 2. 获取页面块列表
        logger.info("📋 获取页面块列表...")
        await extractor._rate_limit_wait()
        from notion_client.helpers import async_collect_paginated_api
        blocks = await async_collect_paginated_api(
            extractor.client.blocks.children.list,
            block_id=page_id
        )
        
        logger.info(f"找到 {len(blocks)} 个块")
        
        # 3. 分析每个块
        file_blocks = []
        for i, block in enumerate(blocks):
            block_type = block.get("type", "")
            block_id = block.get("id", "")
            
            logger.info(f"块 {i+1}: 类型={block_type}, ID={block_id}")
            
            # 检查是否是文件块
            if block_type in ["file", "pdf", "image", "video", "audio"]:
                logger.info(f"🎯 发现文件块: {block_type}")
                file_blocks.append(block)
                
                # 详细分析文件块结构
                file_obj = block.get(block_type, {})
                logger.info(f"文件对象完整结构: {file_obj}")
                
                # 检查文件对象的各个字段
                if "name" in file_obj:
                    logger.info(f"文件名: {file_obj['name']}")
                if "caption" in file_obj:
                    caption_text = "".join([item.get("plain_text", "") for item in file_obj.get("caption", [])])
                    logger.info(f"文件说明: {caption_text}")
                
                # 检查托管类型
                if "external" in file_obj:
                    logger.info(f"外部链接: {file_obj['external']}")
                elif "file" in file_obj:
                    logger.info(f"Notion托管: {file_obj['file']}")
                elif "file_upload" in file_obj:
                    logger.info(f"上传文件: {file_obj['file_upload']}")
                
                # 提取文件信息
                file_info = extractor._extract_file_metadata(file_obj)
                logger.info(f"提取的文件信息: {file_info}")
                
                # 尝试提取内容
                if block_type in ["file", "pdf"] and file_info.get("file_type") in ["pdf", "docx", "xlsx"]:
                    logger.info("🔄 尝试提取文件内容...")
                    try:
                        content = await extractor._extract_file_content(block)
                        logger.info(f"提取结果长度: {len(content) if content else 0}")
                        if content:
                            logger.info(f"提取结果预览: {content[:300]}...")
                    except Exception as e:
                        logger.error(f"提取失败: {e}")
                else:
                    logger.info(f"跳过内容提取: 类型={file_info.get('file_type')}, 块类型={block_type}")
        
        # 4. 测试完整内容获取
        logger.info("📖 测试完整内容获取...")
        try:
            # 不包含文件
            content_no_files = await client.get_page_content(page_id, include_files=False)
            logger.info(f"不含文件的内容长度: {len(content_no_files) if content_no_files else 0}")
            
            # 包含文件
            content_with_files = await client.get_page_content(page_id, include_files=True)
            logger.info(f"含文件的内容长度: {len(content_with_files) if content_with_files else 0}")
            
            if content_with_files:
                logger.info(f"含文件的内容预览:\n{content_with_files[:500]}...")
            
        except Exception as e:
            logger.error(f"完整内容获取失败: {e}")
        
        # 总结
        logger.info(f"📊 调试总结:")
        logger.info(f"- 总块数: {len(blocks)}")
        logger.info(f"- 文件块数: {len(file_blocks)}")
        logger.info(f"- 文件块类型: {[b.get('type') for b in file_blocks]}")
        
        return file_blocks
        
    except Exception as e:
        logger.exception(f"❌ 调试过程出错: {e}")
        return []

async def main():
    """主函数"""
    if len(sys.argv) != 2:
        print("用法: python debug_file_extraction.py <page_id>")
        print("示例: python debug_file_extraction.py 123e4567-e89b-12d3-a456-426614174000")
        sys.exit(1)
    
    page_id = sys.argv[1]
    
    # 清理page_id格式并转换为标准UUID格式
    page_id = page_id.replace("https://www.notion.so/", "").split("?")[0]
    
    # 如果包含"-"，提取实际ID部分
    if "-" in page_id:
        page_id = page_id.split("-")[-1]
    
    # 转换为标准UUID格式 (8-4-4-4-12)
    if len(page_id) == 32 and "-" not in page_id:
        page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:32]}"
    
    logger.info(f"调试页面ID: {page_id}")
    
    file_blocks = await debug_page_file_extraction(page_id)
    
    if file_blocks:
        logger.info(f"✅ 找到 {len(file_blocks)} 个文件块")
    else:
        logger.warning("⚠️ 没有找到文件块，可能:")
        logger.warning("1. 页面确实没有文件")
        logger.warning("2. 文件类型不被识别")
        logger.warning("3. 权限问题")

if __name__ == "__main__":
    asyncio.run(main())