"""
WeChat关系图谱数据模型
专门用于处理微信聊天数据的结构化模型
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from enum import Enum


class EpisodeType(str, Enum):
    """Episode类型枚举"""
    PERSON_IDENTITY = "person_identity"      # 人员身份
    GROUP_CONTEXT = "group_context"          # 群组/上下文
    PERSON_RELATIONSHIP = "person_relationship"  # 人际关系
    GROUP_MEMBERSHIP = "group_membership"     # 群组成员关系
    ACTIVITY_PARTICIPATION = "activity_participation"  # 活动参与
    SOCIAL_SCENARIO = "social_scenario"       # 综合社交场景


class RelationshipType(str, Enum):
    """关系类型枚举"""
    COLLEAGUE = "colleague"           # 同事
    PROJECT_COLLABORATOR = "project_collaborator"  # 项目合作者
    FRIEND = "friend"                # 朋友
    FAMILY = "family"               # 家人
    CLASSMATE = "classmate"         # 同学
    UNKNOWN = "unknown"             # 未知关系


class WeChatUser(BaseModel):
    """微信用户模型"""
    original_name: str = Field(..., description="原始微信昵称")
    cleaned_name: str = Field(..., description="清洗后的标准化昵称")
    wechat_id: Optional[str] = Field(None, description="微信ID（如果可获取）")
    user_type: str = Field(default="user", description="用户类型")
    
    @field_validator('cleaned_name')
    def validate_cleaned_name(cls, v):
        """验证清洗后的昵称"""
        if not v or len(v.strip()) == 0:
            raise ValueError("清洗后的昵称不能为空")
        return v.strip()


class WeChatGroup(BaseModel):
    """微信群组模型"""
    group_name: str = Field(..., description="群组名称")
    group_type: str = Field(..., description="群组类型，如'工作群组'、'朋友群'等")
    description: Optional[str] = Field(None, description="群组描述")
    members: List[WeChatUser] = Field(default_factory=list, description="群组成员列表")
    topic: Optional[str] = Field(None, description="群组主题")
    
    @field_validator('group_name')
    def validate_group_name(cls, v):
        """验证群组名称"""
        if not v or len(v.strip()) == 0:
            raise ValueError("群组名称不能为空")
        return v.strip()


class WeChatRelationship(BaseModel):
    """微信关系模型"""
    person_a: str = Field(..., description="关系中的第一人（清洗后昵称）")
    person_b: str = Field(..., description="关系中的第二人（清洗后昵称）")
    relationship_type: RelationshipType = Field(..., description="关系类型")
    context: Optional[str] = Field(None, description="关系上下文，如群组名称")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="关系置信度")
    
    @field_validator('person_a', 'person_b')
    def validate_person_names(cls, v):
        """验证人员名称"""
        if not v or len(v.strip()) == 0:
            raise ValueError("人员名称不能为空")
        return v.strip()


class WeChatActivity(BaseModel):
    """微信活动模型"""
    activity_date: datetime = Field(..., description="活动日期")
    participant: str = Field(..., description="参与者（清洗后昵称）")
    group_context: str = Field(..., description="活动上下文（群组名称）")
    activity_type: str = Field(default="group_chat", description="活动类型")
    
    @field_validator('participant', 'group_context')
    def validate_activity_fields(cls, v):
        """验证活动字段"""
        if not v or len(v.strip()) == 0:
            raise ValueError("活动字段不能为空")
        return v.strip()


class WeChatEpisode(BaseModel):
    """微信Episode模型 - 转换为Graphiti可理解的文本片段"""
    episode_id: str = Field(..., description="Episode唯一标识")
    episode_type: EpisodeType = Field(..., description="Episode类型")
    content: str = Field(..., description="Episode文本内容")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Episode元数据")
    source_file: str = Field(..., description="来源文件路径")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    
    @field_validator('content')
    def validate_content(cls, v):
        """验证Episode内容"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Episode内容不能为空")
        return v.strip()
    
    @field_validator('episode_id')
    def validate_episode_id(cls, v):
        """验证Episode ID"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Episode ID不能为空")
        return v.strip()


class WeChatChatMessage(BaseModel):
    """微信聊天消息原始模型"""
    sender: str = Field(..., description="发送者原始昵称")
    message: str = Field(..., description="消息内容")
    timestamp: datetime = Field(..., description="消息时间戳")
    message_type: str = Field(default="text", description="消息类型")
    
    @field_validator('sender')
    def validate_sender(cls, v):
        """验证发送者"""
        if not v or len(v.strip()) == 0:
            raise ValueError("发送者不能为空")
        return v.strip()


class WeChatChatFile(BaseModel):
    """微信聊天文件模型"""
    file_path: str = Field(..., description="文件路径")
    group_name: str = Field(..., description="群组名称")
    chat_date: datetime = Field(..., description="聊天日期")
    messages: List[WeChatChatMessage] = Field(default_factory=list, description="聊天消息列表")
    processed: bool = Field(default=False, description="是否已处理")
    
    @field_validator('file_path')
    def validate_file_path(cls, v):
        """验证文件路径"""
        if not v or len(v.strip()) == 0:
            raise ValueError("文件路径不能为空")
        return v.strip()


class WeChatDataProcessor(BaseModel):
    """微信数据处理器配置"""
    input_directory: str = Field(..., description="输入目录路径")
    output_directory: str = Field(..., description="输出目录路径")
    name_cleaning_rules: Dict[str, str] = Field(default_factory=dict, description="姓名清洗规则")
    deduplication_enabled: bool = Field(default=True, description="是否启用去重")
    activity_deduplication_enabled: bool = Field(default=False, description="活动是否去重")
    
    @field_validator('input_directory', 'output_directory')
    def validate_directories(cls, v):
        """验证目录路径"""
        if not v or len(v.strip()) == 0:
            raise ValueError("目录路径不能为空")
        return v.strip()


class EpisodeGenerationResult(BaseModel):
    """Episode生成结果模型"""
    success: bool = Field(..., description="生成是否成功")
    total_episodes: int = Field(default=0, description="生成的Episode总数")
    episodes_by_type: Dict[str, int] = Field(default_factory=dict, description="按类型统计的Episode数量")
    processed_files: List[str] = Field(default_factory=list, description="已处理的文件列表")
    errors: List[str] = Field(default_factory=list, description="错误信息列表")
    processing_time_seconds: float = Field(default=0.0, description="处理时间（秒）")


class QueryAnalysisResult(BaseModel):
    """查询分析结果模型"""
    query_type: str = Field(..., description="查询类型")
    key_entities: Dict[str, List[str]] = Field(default_factory=dict, description="关键实体")
    core_intent: str = Field(..., description="核心意图")
    search_keywords: List[str] = Field(default_factory=list, description="搜索关键词")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="分析置信度")


class RelationshipSearchRequest(BaseModel):
    """关系搜索请求模型"""
    query: str = Field(..., description="搜索查询")
    search_type: str = Field(default="relationship", description="搜索类型")
    max_results: int = Field(default=5, ge=1, le=20, description="最大结果数")
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="置信度阈值")
    
    @field_validator('query')
    def validate_query(cls, v):
        """验证查询内容"""
        if not v or len(v.strip()) == 0:
            raise ValueError("查询内容不能为空")
        return v.strip()


class RelationshipSearchResult(BaseModel):
    """关系搜索结果模型"""
    success: bool = Field(..., description="搜索是否成功")
    query_analysis: Optional[QueryAnalysisResult] = Field(None, description="查询分析结果")
    episodes: List[str] = Field(default_factory=list, description="相关Episode列表")
    formatted_answer: str = Field(default="", description="格式化的答案")
    processing_time_ms: float = Field(default=0.0, description="处理时间（毫秒）")
    error: Optional[str] = Field(None, description="错误信息")


# 工具函数
def clean_wechat_name(original_name: str) -> str:
    """
    清洗微信昵称的标准化函数
    
    Args:
        original_name: 原始微信昵称
        
    Returns:
        str: 清洗后的昵称
    """
    if not original_name:
        return "未知用户"
    
    # 移除常见的装饰性字符
    cleaned = original_name.strip()
    
    # 移除emoji和特殊符号的基本规则
    import re
    
    # 移除emoji表情
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE
    )
    cleaned = emoji_pattern.sub('', cleaned)
    
    # 移除特殊装饰符号
    special_chars = ['ゞ', 'の', '✨', '🌟', '⭐', '💫', '🔥', '💪', '👍', '❤️', '💙', '💚', '💛', '💜', '🧡']
    for char in special_chars:
        cleaned = cleaned.replace(char, '')
    
    # 移除多余的空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # 如果清洗后为空，返回原始名称的前几个字符
    if not cleaned:
        return original_name[:5] if len(original_name) > 5 else original_name
    
    return cleaned


def generate_episode_id(episode_type: EpisodeType, content: str) -> str:
    """
    生成Episode唯一ID
    
    Args:
        episode_type: Episode类型
        content: Episode内容
        
    Returns:
        str: 唯一ID
    """
    import hashlib
    
    # 使用类型和内容的哈希值生成ID
    content_hash = hashlib.md5(f"{episode_type.value}:{content}".encode('utf-8')).hexdigest()
    return f"{episode_type.value}_{content_hash[:8]}"


def infer_relationship_type(context: str, group_name: str) -> RelationshipType:
    """
    根据上下文推断关系类型
    
    Args:
        context: 关系上下文
        group_name: 群组名称
        
    Returns:
        RelationshipType: 推断的关系类型
    """
    # 基于群组名称的简单推断规则
    group_lower = group_name.lower()
    
    if any(keyword in group_lower for keyword in ['工作', '项目', '研发', '开发', '团队', 'team', 'work']):
        return RelationshipType.PROJECT_COLLABORATOR
    elif any(keyword in group_lower for keyword in ['朋友', '同学', '班级', 'friend', 'class']):
        return RelationshipType.FRIEND
    elif any(keyword in group_lower for keyword in ['家庭', '家人', 'family']):
        return RelationshipType.FAMILY
    else:
        return RelationshipType.COLLEAGUE  # 默认为同事关系