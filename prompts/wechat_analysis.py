"""
微信关系分析提示词模板
用于Gemini模型的查询分析和结果格式化
"""

from langchain.prompts import PromptTemplate
from typing import List, Dict, Any
from core.wechat_models import QueryAnalysisResult


class WeChatAnalysisPrompt:
    """微信关系分析提示词管理器"""
    
    def __init__(self):
        self.query_analysis_template = self._create_query_analysis_template()
        self.result_format_template = self._create_result_format_template()
    
    def _create_query_analysis_template(self) -> PromptTemplate:
        """创建查询分析提示词模板"""
        template = """
你是一个专业的微信关系图谱分析助手。请分析用户的查询意图，并提取关键信息用于图谱搜索。

用户查询："{query}"

请分析并返回以下信息：
1. 查询类型（person_relationship, group_info, activity_search, general）
2. 关键实体（人名、群组名等）
3. 核心意图
4. 搜索关键词

请以JSON格式返回结果：
{{
    "query_type": "查询类型",
    "key_entities": {{
        "persons": ["人名1", "人名2"],
        "groups": ["群组1", "群组2"],
        "activities": ["活动1", "活动2"]
    }},
    "core_intent": "核心意图描述",
    "search_keywords": ["关键词1", "关键词2", "关键词3"],
    "confidence": 0.8
}}

分析要求：
- 准确识别查询中的人名和群组名
- 提取有助于图谱搜索的关键词
- 判断查询的核心意图
- 对分析结果给出置信度评分

只返回JSON，不要其他内容。
"""
        return PromptTemplate(
            template=template,
            input_variables=["query"]
        )
    
    def _create_result_format_template(self) -> PromptTemplate:
        """创建结果格式化提示词模板"""
        template = """
你是一个专业的微信关系图谱分析助手。请根据用户的查询和搜索到的Episode信息，生成清晰、准确的答案。

用户查询："{query}"

查询分析结果：
- 查询类型：{query_type}
- 核心意图：{core_intent}
- 关键实体：{key_entities}

相关Episode信息：
{episodes}

请基于上述信息，生成一个清晰、准确的回答。要求：
1. 直接回答用户的问题
2. 根据Episode信息提供具体的关系、角色或活动信息
3. 如果信息不足，说明现有信息的局限性
4. 保持回答的客观性和准确性

请生成格式化的回答：
"""
        return PromptTemplate(
            template=template,
            input_variables=["query", "query_type", "core_intent", "key_entities", "episodes"]
        )
    
    def create_query_analysis_prompt(self, query: str) -> str:
        """创建查询分析提示词"""
        return self.query_analysis_template.format(query=query)
    
    def create_result_format_prompt(
        self, 
        query: str, 
        analysis: QueryAnalysisResult,
        episodes: List[str]
    ) -> str:
        """创建结果格式化提示词"""
        # 将Episode列表转换为格式化字符串
        episodes_text = "\n".join([f"- {episode}" for episode in episodes])
        
        return self.result_format_template.format(
            query=query,
            query_type=analysis.query_type,
            core_intent=analysis.core_intent,
            key_entities=str(analysis.key_entities),
            episodes=episodes_text
        )
    
    def create_episode_generation_prompt(self, chat_data: Dict[str, Any]) -> str:
        """创建Episode生成提示词"""
        template = """
你是一个微信聊天数据分析专家。请分析以下微信群聊数据，提取出有用的关系信息。

聊天数据：
群组：{group_name}
日期：{date}
参与者：{participants}

请根据数据生成以下类型的结构化Episode：
1. 人员身份信息
2. 群组上下文信息
3. 人际关系信息
4. 群组成员关系
5. 活动参与信息
6. 综合社交场景

每个Episode应该是一个完整的、有意义的语句，便于后续的图谱搜索。

请以JSON格式返回：
{{
    "episodes": [
        {{
            "type": "person_identity",
            "content": "Episode内容",
            "metadata": {{"participant": "参与者"}}
        }},
        ...
    ]
}}
"""
        return template.format(
            group_name=chat_data.get('group_name', ''),
            date=chat_data.get('date', ''),
            participants=', '.join(chat_data.get('participants', []))
        )