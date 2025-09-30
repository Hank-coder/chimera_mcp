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
    parentId: Optional[str] = Field(None, description="Parent page ID for hierarchy")
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
        parentId=extract_parent_id_from_page(page_data)
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
    max_results: int = Field(default=5, ge=1, le=10, description="最大结果数量")
    speed: bool = Field(default=False, description="速度模式：True=只使用embedding搜索，False=混合搜索")


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
    # 添加时间信息
    last_edited_time: Optional[str] = Field(None, description="叶子节点最后编辑时间")
    # 🆕 混合搜索相关字段
    search_source: Optional[str] = Field(None, description="搜索来源：llm_judgment 或 embedding")
    semantic_score: Optional[float] = Field(None, description="语义相似度得分（embedding搜索）")


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
    model_name: str = Field(default="gemini-2.5-flash", description="模型名称")


class GeminiAPIResponse(BaseModel):
    """Gemini API响应模型"""
    success: bool = Field(..., description="请求是否成功")
    content: Optional[str] = Field(None, description="响应内容")
    error: Optional[str] = Field(None, description="错误信息")
    usage_info: Optional[Dict[str, Any]] = Field(None, description="使用信息")


# Deep Research 相关模型
class DeepResearchRequest(BaseModel):
    """Deep Research内部请求模型"""
    page_id: str = Field(..., description="根页面ID")
    purpose: str = Field(..., description="研究目的和关注点，用于关联度判断")
    max_pages: int = Field(default=10, ge=5, le=20, description="返回页面数量，最大20")
    research_complexity: str = Field(
        default="standard", 
        description="研究复杂度：overview|standard|detailed|comprehensive"
    )
    
    # 内部固定参数
    depth: int = Field(default=4, description="固定遍历深度")
    max_workers: int = Field(default=6, description="固定Worker数量")


class ResearchComplexityConfig(BaseModel):
    """研究复杂度配置"""
    complexity_type: str = Field(..., description="复杂度类型")
    summary_style: str = Field(..., description="摘要风格")
    focus_areas: List[str] = Field(..., description="关注领域")
    compression_ratio: float = Field(..., ge=0.1, le=1.0, description="压缩比例")
    detail_level: str = Field(..., description="详细程度")
    target_summary_length: int = Field(..., description="目标摘要长度（字符数）")


class PageAnalysis(BaseModel):
    """页面分析结果"""
    notion_id: str = Field(..., description="页面ID")
    title: str = Field(..., description="页面标题")
    content: str = Field(..., description="原始内容")
    summary: str = Field(..., description="AI生成的页面摘要")
    key_points: List[str] = Field(..., description="关键要点列表")
    importance_score: float = Field(..., description="重要性评分，0.0-1.0之间")
    relevance_score: float = Field(..., description="与研究目的的关联度评分，0.0-1.0之间")
    word_count: int = Field(..., description="字数统计")
    supporting_quotes: List[str] = Field(..., description="支撑引用")
    research_value: Dict[str, str] = Field(..., description="研究价值评估")


class TopicCluster(BaseModel):
    """主题簇分析结果"""
    cluster_id: str = Field(..., description="簇ID")
    theme: str = Field(..., description="主题描述")
    pages: List[PageAnalysis] = Field(..., description="页面分析列表")
    cluster_synthesis: str = Field(..., description="簇级综合摘要")
    representative_quotes: List[str] = Field(..., description="代表性引用")
    cross_references: List[str] = Field(..., description="交叉引用")


class ResearchFramework(BaseModel):
    """研究框架"""
    problem_definition: str = Field(..., description="问题定义")
    theoretical_foundation: str = Field(..., description="理论基础")
    methodology_insights: str = Field(..., description="方法论洞察")
    expected_contributions: str = Field(..., description="预期贡献")


class ResearchContext(BaseModel):
    """Deep Research最终输出模型"""
    executive_summary: str = Field(..., description="执行摘要")
    topic_clusters: List[TopicCluster] = Field(..., description="主题簇列表")
    top_pages: List[PageAnalysis] = Field(..., description="顶级页面分析")
    key_insights: List[str] = Field(..., description="核心洞察")
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list, description="支撑证据")
    research_framework: ResearchFramework = Field(..., description="研究框架")
    future_directions: List[str] = Field(default_factory=list, description="未来方向")
    research_scope: Dict[str, Any] = Field(default_factory=dict, description="研究范围元信息")


class DeepResearchResponse(BaseModel):
    """Deep Research MCP响应模型"""
    success: bool = Field(..., description="研究是否成功")
    research_context: Optional[ResearchContext] = Field(None, description="研究上下文")
    complexity_applied: str = Field(..., description="应用的复杂度")
    pages_analyzed: int = Field(..., description="分析的页面数")
    processing_metadata: Dict[str, Any] = Field(default_factory=dict, description="处理元数据")
    error: Optional[str] = Field(None, description="错误信息")


# Gemini structured output schemas
class ClusteringResult(BaseModel):
    """语义分簇结果schema"""
    clusters: List[Dict[str, Any]] = Field(description="分簇结果列表")
    reasoning: str = Field(description="分簇理由")

class ClusteringResponse(BaseModel):
    """分簇响应schema"""
    clustering_result: ClusteringResult = Field(description="分簇结果")

class PageAnalysisResult(BaseModel):
    """页面分析结果schema"""
    summary: str = Field(description="页面摘要")
    key_points: List[str] = Field(description="关键要点")
    importance_score: float = Field(description="重要性评分，0.0-1.0之间")
    relevance_score: float = Field(description="关联度评分，0.0-1.0之间")
    supporting_quotes: List[str] = Field(description="支撑引用")
    research_value: Dict[str, str] = Field(description="研究价值")

class PageAnalysisResponse(BaseModel):
    """页面分析响应schema"""
    page_analysis: PageAnalysisResult = Field(..., description="页面分析结果")

class ClusterSynthesisResult(BaseModel):
    """簇综合结果schema"""
    synthesis: str = Field(description="簇综合摘要")
    key_themes: List[str] = Field(description="关键主题")
    cross_references: List[str] = Field(description="交叉引用")
    methodology_insights: str = Field(description="方法论洞察")

class ClusterSynthesisResponse(BaseModel):
    """簇综合响应schema"""
    cluster_synthesis: ClusterSynthesisResult = Field(..., description="簇综合结果")

# 研究复杂度配置常量
RESEARCH_COMPLEXITY_CONFIGS = {
    "overview": ResearchComplexityConfig(
        complexity_type="overview",
        summary_style="executive_summary",
        focus_areas=["核心结论", "主要趋势", "关键洞察"],
        compression_ratio=0.3,
        detail_level="high_level",
        target_summary_length=800
    ),
    "standard": ResearchComplexityConfig(
        complexity_type="standard", 
        summary_style="balanced_analysis",
        focus_areas=["核心观点", "支撑证据", "实用建议"],
        compression_ratio=0.5,
        detail_level="medium",
        target_summary_length=1200
    ),
    "detailed": ResearchComplexityConfig(
        complexity_type="detailed",
        summary_style="thorough_analysis", 
        focus_areas=["理论基础", "方法论", "案例分析", "实践应用"],
        compression_ratio=0.6,
        detail_level="comprehensive",
        target_summary_length=1800
    ),
    "comprehensive": ResearchComplexityConfig(
        complexity_type="comprehensive",
        summary_style="academic_research",
        focus_areas=["理论框架", "文献脉络", "方法论", "实证分析", "创新贡献", "未来方向"],
        compression_ratio=0.8, 
        detail_level="exhaustive",
        target_summary_length=2500
    )
}


# ==================== GPT MCP标准工具模型 ====================
# 符合GPT MCP标准的search和fetch工具的Pydantic模型定义

class SearchToolInput(BaseModel):
    """GPT MCP标准search工具输入模型 - ChatGPT兼容"""
    query: str = Field(..., description="搜索查询字符串")


class SearchResultItem(BaseModel):
    """单个搜索结果项"""
    id: str = Field(..., description="Notion页面ID")
    title: str = Field(..., description="页面标题")
    url: str = Field(..., description="页面URL")


class SearchToolResponse(BaseModel):
    """Search工具响应（GPT MCP标准格式）"""
    results: List[SearchResultItem] = Field(..., description="搜索结果列表")


class FetchToolInput(BaseModel):
    """GPT MCP标准fetch工具输入模型 - ChatGPT兼容，支持单ID或多ID"""
    page_id: str = Field(
        ...,
        description=(
            "页面ID字符串，支持三种格式：\n"
            "1. 单个ID: 'page-id-1'\n"
            "2. 逗号分隔: 'page-id-1,page-id-2,page-id-3'\n"
            "3. JSON数组: '[\"page-id-1\", \"page-id-2\"]'"
        )
    )


class FetchResultItem(BaseModel):
    """单个fetch结果项"""
    id: str = Field(..., description="页面ID")
    title: str = Field(..., description="页面标题")
    text: str = Field(..., description="页面完整文本内容")
    url: str = Field(..., description="页面URL")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="页面元数据")


class FetchToolResponse(BaseModel):
    """Fetch工具响应（GPT MCP标准格式）"""
    results: List[FetchResultItem] = Field(..., description="获取结果列表")


# ==================== 个人记忆写入工具模型 ====================

class PersonalMemoryInput(BaseModel):
    """个人记忆写入输入模型"""
    content: str = Field(
        ...,
        description=(
            "要记忆的内容，使用自然语言描述。\n"
            "可以使用第一人称'我'，系统会理解为陈宇函。\n\n"
            "示例:\n"
            "- '我和JZX是同事，他擅长前端开发'\n"
            "- '我参与了GREEN项目的kick-off会议'\n"
            "- '我喜欢早上喝咖啡'\n"
            "- 'JZX推荐我看《代码大全》这本书'"
        )
    )
    memory_type: str = Field(
        default="relationship",
        description=(
            "记忆类型:\n"
            "- relationship: 人际关系（默认）\n"
            "- preference: 个人偏好\n"
            "- event: 事件参与\n"
            "- fact: 事实记录"
        )
    )


class PersonalMemoryResponse(BaseModel):
    """个人记忆写入响应模型"""
    success: bool = Field(..., description="写入是否成功")
    message: str = Field(..., description="响应消息")
    memory_id: Optional[str] = Field(None, description="记忆唯一ID")