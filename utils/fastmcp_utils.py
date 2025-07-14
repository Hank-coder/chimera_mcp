"""
FastMCP 工具函数
包含MCP服务器的辅助函数，保持主服务器文件简洁
"""
from typing import List, Dict, Any
from loguru import logger


def get_bearer_token(ctx):
    """
    从FastMCP上下文中获取Bearer token
    """
    request = ctx.get_http_request()
    headers = request.headers
    # Check if 'Authorization' header is present
    authorization_header = headers.get('Authorization')
    
    if authorization_header:
        # Split the header into 'Bearer <token>'
        parts = authorization_header.split()
        
        if len(parts) == 2 and parts[0] == 'Bearer':
            return parts[1]
        else:
            raise ValueError("Invalid Authorization header format")
    else:
        raise ValueError("Authorization header missing")


async def get_path_contents_async(notion_client, path_titles: List[str], path_ids: List[str], 
                                 include_files: bool = True, max_content_length: int = 8000, 
                                 max_file_content_length: int = 8000) -> List[Dict[str, Any]]:
    """
    获取路径中所有页面的内容，支持文档提取和长度控制
    
    Args:
        notion_client: Notion客户端实例
        path_titles: 页面标题列表
        path_ids: 页面ID列表
        include_files: 是否提取文档内容
        max_content_length: 单个页面内容最大长度
        max_file_content_length: 单个文档内容最大长度
        
    Returns:
        包含页面内容的字典列表
    """
    if not notion_client:
        from core.notion_client import NotionClient
        notion_client = NotionClient()
    
    # 临时设置文件提取器的长度限制
    from core.file_extractor import file_extractor
    original_max_length = file_extractor.max_content_length
    if max_file_content_length > 0:
        file_extractor.max_content_length = max_file_content_length
    
    path_contents = []
    
    try:
        for i, (title, page_id) in enumerate(zip(path_titles, path_ids)):
            try:
                # 根据参数决定是否提取文档内容
                if include_files:
                    content = await notion_client.get_page_content(
                        page_id, 
                        include_files=True, 
                        max_length=max_content_length
                    )
                else:
                    content = await notion_client.get_page_content(
                        page_id, 
                        include_files=False, 
                        max_length=max_content_length
                    )
                
                # 额外的长度控制（防止单个页面过长）
                if max_content_length > 0 and len(content) > max_content_length:
                    content = truncate_content_smart(content, max_content_length)
                
                path_contents.append({
                    "position": i,
                    "title": title,
                    "notion_id": page_id,
                    "content": content,
                    "has_files": include_files,
                    "content_length": len(content)
                })
            except Exception as e:
                error_msg = str(e)
                
                # 页面获取失败，返回友好错误信息
                if ("Could not find block with ID" in error_msg or 
                    "Make sure the relevant pages and databases are shared" in error_msg or
                    "页面不存在或未授权访问" in error_msg):
                    
                    logger.warning(f"页面 {page_id} 无法访问: {error_msg}")
                    
                    path_contents.append({
                        "position": i,
                        "title": title,
                        "notion_id": page_id,
                        "content": f"⚠️ 页面无法访问: {title}\n原因: 页面已删除或权限不足",
                        "has_files": False,
                        "content_length": 0,
                        "status": "inaccessible"
                    })
                else:
                    # 其他错误
                    path_contents.append({
                        "position": i,
                        "title": title,
                        "notion_id": page_id,
                        "content": f"获取内容失败: {error_msg}",
                        "has_files": False,
                        "content_length": 0,
                        "status": "error"
                    })
    finally:
        # 恢复原始设置
        file_extractor.max_content_length = original_max_length
    
    return path_contents


def truncate_content_smart(content: str, max_length: int) -> str:
    """
    截断内容，保留重要部分
    
    Args:
        content: 原始内容
        max_length: 最大长度
        
    Returns:
        截断后的内容
    """
    if len(content) <= max_length:
        return content
    
    # 保留前80%和后10%的内容
    front_length = int(max_length * 0.8)
    back_length = int(max_length * 0.1)
    
    front_part = content[:front_length]
    back_part = content[-back_length:] if back_length > 0 else ""
    
    truncated = front_part
    if back_part:
        truncated += f"\n\n... [内容已截断，省略 {len(content) - front_length - back_length} 字符] ...\n\n" + back_part
    else:
        truncated += f"\n\n[内容已截断: 显示 {front_length}/{len(content)} 字符]"
    
    return truncated