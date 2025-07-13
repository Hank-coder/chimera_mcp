from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class NodeType(str, Enum):
    PAGE = "page"
    DATABASE = "database"
    BLOCK = "block"
    TAG = "tag"


class RelationType(str, Enum):
    CHILD_OF = "CHILD_OF"
    LINKS_TO = "LINKS_TO"
    RELATED_TO = "RELATED_TO"
    MENTIONS = "MENTIONS"
    HAS_TAG = "HAS_TAG"


class NotionPageMetadata(BaseModel):
    """
    Core data model for NotionPage nodes in the graph.
    Follows the "Graph as Index" principle - stores only metadata and relationships.
    """
    notion_id: str = Field(..., description="Unique identifier from Notion API")
    title: str = Field(..., description="Page title for identification and basic search")
    type: NodeType = Field(..., description="Type of Notion object (page, database, block)")
    tags: List[str] = Field(default_factory=list, description="Page tags for topic clustering")
    last_edited_time: datetime = Field(..., description="Last modification time for incremental sync")
    url: str = Field(..., description="Direct URL to the Notion page")
    parent_id: Optional[str] = Field(None, description="Parent page ID for hierarchy")
    level: int = Field(default=0, description="Page hierarchy level (0=root, 1=child, 2=grandchild, etc.)")
    
    # Extracted relationship data
    internal_links: List[str] = Field(default_factory=list, description="Internal links found in page content")
    mentions: List[str] = Field(default_factory=list, description="@mentions found in page content")
    database_relations: List[str] = Field(default_factory=list, description="Database relation property IDs")
    
    # Metadata for sync optimization
    content_hash: Optional[str] = Field(None, description="Hash of content for change detection")
    sync_status: str = Field(default="pending", description="Sync status (pending, synced, error)")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class SearchQuery(BaseModel):
    """
    Model for search queries to the MCP server.
    """
    query: str = Field(..., description="Search query string")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of results")
    include_content: bool = Field(default=False, description="Whether to include page content in results")
    filters: Optional[Dict[str, Any]] = Field(None, description="Additional filters for search")


class SearchResult(BaseModel):
    """
    Model for search results from the MCP server.
    """
    notion_id: str = Field(..., description="Notion page ID")
    title: str = Field(..., description="Page title")
    url: str = Field(..., description="Direct URL to page")
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="Relevance score for the query")
    tags: List[str] = Field(default_factory=list, description="Page tags")
    content: Optional[str] = Field(None, description="Page content if requested")
    relationship_context: Optional[str] = Field(None, description="How this page relates to the query")


class ExpandResult(BaseModel):
    """
    Model for expand results from graph traversal.
    """
    page_id: str = Field(..., description="Page ID")
    title: str = Field(..., description="Page title")
    url: str = Field(..., description="Direct URL to page")
    depth: int = Field(..., description="Distance from starting nodes")
    path: List[str] = Field(..., description="Path of relationship types to reach this node")
    tags: List[str] = Field(default_factory=list, description="Page tags")


class SyncReport(BaseModel):
    """
    Model for sync operation reports.
    """
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = Field(None)
    pages_processed: int = Field(default=0)
    pages_created: int = Field(default=0)
    pages_updated: int = Field(default=0)
    pages_deleted: int = Field(default=0)
    relationships_created: int = Field(default=0)
    relationships_updated: int = Field(default=0)
    relationships_deleted: int = Field(default=0)
    errors: List[str] = Field(default_factory=list)
    status: str = Field(default="running")  # running, completed, failed
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class GraphStats(BaseModel):
    """
    Model for graph statistics.
    """
    total_pages: int = Field(default=0)
    total_relationships: int = Field(default=0)
    relationship_counts: Dict[str, int] = Field(default_factory=dict)
    most_connected_pages: List[Dict[str, Any]] = Field(default_factory=list)
    last_sync: Optional[datetime] = Field(None)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# Validation functions
def validate_notion_id(notion_id: str) -> str:
    """Validate Notion ID format."""
    if not notion_id or len(notion_id) != 32:
        raise ValueError("Invalid Notion ID format")
    return notion_id




# Factory functions
def create_notion_page_from_api(page_data: Dict[str, Any]) -> NotionPageMetadata:
    """Create NotionPageMetadata from Notion API response."""
    return NotionPageMetadata(
        notion_id=page_data["id"],
        title=extract_title_from_page(page_data),
        type=NodeType.PAGE,
        tags=extract_tags_from_page(page_data),
        last_edited_time=datetime.fromisoformat(page_data["last_edited_time"].replace("Z", "+00:00")),
        url=page_data["url"],
        parent_id=extract_parent_id_from_page(page_data)
    )


def extract_title_from_page(page_data: Dict[str, Any]) -> str:
    """Extract title from Notion page data."""
    properties = page_data.get("properties", {})
    for prop_data in properties.values():
        if prop_data.get("type") == "title":
            title_array = prop_data.get("title", [])
            if title_array:
                return "".join([item.get("plain_text", "") for item in title_array])
    return "Untitled"


def extract_tags_from_page(page_data: Dict[str, Any]) -> List[str]:
    """Extract tags from Notion page data."""
    tags = []
    properties = page_data.get("properties", {})
    for prop_data in properties.values():
        if prop_data.get("type") == "multi_select":
            for option in prop_data.get("multi_select", []):
                tags.append(option.get("name", ""))
    return tags


def extract_parent_id_from_page(page_data: Dict[str, Any]) -> Optional[str]:
    """Extract parent ID from Notion page data."""
    parent = page_data.get("parent", {})
    if parent.get("type") == "page_id":
        return parent.get("page_id")
    elif parent.get("type") == "database_id":
        return parent.get("database_id")
    return None


# LLM交互相关的Pydantic模型
class ConfidenceEvaluationResponse(BaseModel):
    """Gemini置信度评估响应模型"""
    evaluations: List[Dict[str, Any]] = Field(..., description="评估结果列表")
    summary: Dict[str, Any] = Field(..., description="汇总信息")


class IntentSearchRequest(BaseModel):
    """意图搜索请求模型"""
    intent_keywords: List[str] = Field(..., description="意图关键词列表")
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="置信度阈值")
    max_results: int = Field(default=2, ge=1, le=5, description="最大结果数量")
    expansion_depth: int = Field(default=2, ge=1, le=3, description="路径扩展深度")


class IntentSearchMetadata(BaseModel):
    """意图搜索元数据"""
    initial_candidates: int = Field(..., description="初始候选数量")
    high_confidence_matches: int = Field(..., description="高置信度匹配数量")
    confidence_threshold: float = Field(..., description="置信度阈值")
    processing_time_ms: Optional[float] = Field(None, description="处理时间（毫秒）")


class CorePageResult(BaseModel):
    """核心页面结果"""
    notion_id: str = Field(..., description="Notion页面ID")
    title: str = Field(..., description="页面标题")
    url: str = Field(..., description="页面URL")
    tags: List[str] = Field(default_factory=list, description="页面标签")
    content: str = Field(..., description="页面内容")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="置信度评分")
    # 添加路径信息
    path_string: Optional[str] = Field(None, description="完整路径字符串，如'Hank -> 简历'")
    path_titles: List[str] = Field(default_factory=list, description="路径中所有页面的标题")
    path_ids: List[str] = Field(default_factory=list, description="路径中所有页面的ID")


class RelatedPageResult(BaseModel):
    """相关页面结果"""
    page_id: str = Field(..., description="页面ID")
    title: str = Field(..., description="页面标题")
    url: str = Field(..., description="页面URL")
    content: str = Field(..., description="页面内容")
    depth: int = Field(..., description="路径深度")
    relationship_path: List[str] = Field(..., description="关系路径")


class ConfidencePathMetadata(BaseModel):
    """置信度路径元数据"""
    total_pages: int = Field(..., description="路径总页面数")
    confidence_level: str = Field(..., description="置信度级别")
    expansion_depth: int = Field(..., description="扩展深度")


class ConfidencePath(BaseModel):
    """置信度路径结果"""
    core_page: CorePageResult = Field(..., description="核心页面")
    related_pages: List[RelatedPageResult] = Field(default_factory=list, description="相关页面列表")
    path_metadata: ConfidencePathMetadata = Field(..., description="路径元数据")


class IntentSearchResponse(BaseModel):
    """意图搜索响应模型"""
    success: bool = Field(..., description="搜索是否成功")
    intent_keywords: List[str] = Field(..., description="原始意图关键词")
    search_metadata: Optional[IntentSearchMetadata] = Field(None, description="搜索元数据")
    confidence_paths: List[ConfidencePath] = Field(default_factory=list, description="置信度路径列表")
    total_results: int = Field(..., description="结果总数")
    error: Optional[str] = Field(None, description="错误信息")


class GeminiAPIRequest(BaseModel):
    """Gemini API请求模型"""
    prompt: str = Field(..., description="提示文本")
    temperature: float = Field(default=0.1, ge=0.0, le=2.0, description="温度参数")
    max_output_tokens: int = Field(default=2000, ge=1, le=8192, description="最大输出token数")
    model_name: str = Field(default="gemini-2.0-flash", description="模型名称")


class GeminiAPIResponse(BaseModel):
    """Gemini API响应模型"""
    success: bool = Field(..., description="请求是否成功")
    content: Optional[str] = Field(None, description="响应内容")
    error: Optional[str] = Field(None, description="错误信息")
    usage_info: Optional[Dict[str, Any]] = Field(None, description="使用信息")