"""
意图评估的Prompt模板
使用LangChain的PromptTemplate管理所有与LLM交互的提示词
"""

from langchain.prompts import PromptTemplate
from typing import List, Dict, Any
import json


class IntentEvaluationPrompt:
    """意图评估相关的提示词模板集合"""
    
    def __init__(self):
        # 路径置信度评估模板
        self.confidence_evaluation_template = PromptTemplate(
            input_variables=["user_input", "candidate_paths"],
            template="""
你是一个智能的个人知识库导航助手。用户提出了一个查询，我已经列出了所有可用的完整路径（从根节点到叶子节点）。请从中选择最能回答用户问题的路径。

用户查询：
{user_input}

所有可用的完整路径列表：
{candidate_paths}

请评估每条路径与用户查询的相关性（0-1之间的分数）：
- 1.0：完全匹配用户查询，路径的叶子节点肯定包含答案
- 0.8-0.9：高度相关，路径很可能包含用户需要的信息
- 0.6-0.7：中等相关，路径可能包含部分相关信息
- 0.4-0.5：低度相关，路径可能有一些相关内容
- 0.0-0.3：几乎无关或完全无关

请重点关注：
1. 路径中的关键词（特别是叶子节点）是否匹配用户查询
2. 完整路径的语义是否与查询主题相关
3. 从路径判断最终内容是否能回答用户问题
4. 路径的上下文关系是否有助于理解用户意图

请严格按照以下JSON格式返回，只选择置信度≥0.6的路径：
{{
    "evaluations": [
        {{
            "document_index": 0,
            "confidence_score": 0.85,
            "reasoning": "路径的叶子节点直接匹配用户查询..."
        }},
        {{
            "document_index": 5,
            "confidence_score": 0.72,
            "reasoning": "路径提供了相关的上下文信息..."
        }}
    ],
    "summary": {{
        "total_candidates": {total_count},
        "high_confidence_count": 2,
        "threshold_used": 0.6
    }}
}}

注意：
1. document_index必须对应路径列表的准确索引（从0开始）
2. confidence_score必须是0-1之间的精确数值
3. 只返回置信度≥0.6的路径评估结果
4. reasoning要具体说明为什么这个路径相关
5. 严格使用JSON格式，不要添加markdown或其他格式
"""
        )
        
        # 关键词提取模板
        self.keyword_extraction_template = PromptTemplate(
            input_variables=["user_input"],
            template="""
从以下用户输入中提取3-5个最重要的搜索关键词：

用户输入：{user_input}

请提取能够最好代表用户意图的关键词，优先选择：
1. 主题相关的名词
2. 专业术语
3. 具体的概念或实体名称
4. 动作词汇（如果重要的话）

请严格按照JSON格式返回：
{{
    "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"]
}}

注意：
- 关键词应该是原文中的重要词汇或其同义词
- 优先保留专业术语和具体概念
- 避免常见的停用词（如"的"、"了"、"是"等）
- 严格使用JSON格式
"""
        )
        
        # 语义理解模板
        self.semantic_understanding_template = PromptTemplate(
            input_variables=["user_input", "context_snippets"],
            template="""
请分析用户的查询意图，并评估提供的上下文片段的相关性：

用户查询：{user_input}

上下文片段：
{context_snippets}

请分析：
1. 用户的主要意图是什么
2. 查询中的关键概念有哪些
3. 每个上下文片段与查询的相关性如何

请按以下JSON格式返回：
{{
    "semantic_intent": "用户主要想要...",
    "key_concepts": ["概念1", "概念2", "概念3"],
    "context_relevance": [
        {{
            "context_index": 0,
            "relevance_score": 0.85,
            "relevance_reason": "这个片段直接回答了用户关于...的问题"
        }}
    ],
    "suggested_keywords": ["建议关键词1", "建议关键词2"]
}}
"""
        )
        
        # 路径扩展策略模板
        self.path_expansion_template = PromptTemplate(
            input_variables=["user_query", "current_page", "available_relations"],
            template="""
用户正在查询：{user_query}

当前页面信息：{current_page}

可用的关系路径：{available_relations}

请决定应该沿着哪些关系路径扩展搜索，以最好地回答用户问题：

请按JSON格式返回推荐的扩展策略：
{{
    "recommended_relations": ["LINKS_TO", "RELATED_TO"],
    "expansion_priority": [
        {{
            "relation_type": "LINKS_TO",
            "priority": 0.9,
            "reasoning": "页面间的链接通常包含相关的详细信息"
        }}
    ],
    "max_depth": 2,
    "focus_areas": ["具体要关注的主题1", "主题2"]
}}
"""
        )
    
    def create_evaluation_prompt(self, user_input: str, candidate_paths: List[Dict[str, Any]]) -> str:
        """创建路径置信度评估的完整prompt"""
        
        # 格式化完整路径信息
        formatted_paths = []
        for i, path in enumerate(candidate_paths):
            path_string = path.get('path_string', 'Unknown Path')
            tags_str = ', '.join(path.get('leaf_tags', [])) if path.get('leaf_tags') else '无标签'
            path_length = path.get('path_length', 0)
            path_type = path.get('path_type', 'unknown')
            
            path_info = f"""{i}. "{path_string}"
   - 叶子节点标签: {tags_str}
   - 路径长度: {path_length}
   - 路径类型: {path_type}"""
            formatted_paths.append(path_info)
        
        candidate_paths_str = "\n".join(formatted_paths)
        
        # 替换模板中的total_count占位符
        template_str = self.confidence_evaluation_template.template.replace(
            "{total_count}", str(len(candidate_paths))
        )
        
        return template_str.format(
            user_input=user_input,
            candidate_paths=candidate_paths_str
        )
    
    def create_keyword_extraction_prompt(self, user_input: str) -> str:
        """创建关键词提取prompt"""
        return self.keyword_extraction_template.format(user_input=user_input)
    
    def create_semantic_understanding_prompt(
        self, 
        user_input: str, 
        context_snippets: List[str]
    ) -> str:
        """创建语义理解prompt"""
        
        formatted_snippets = []
        for i, snippet in enumerate(context_snippets):
            formatted_snippets.append(f"片段 {i}: {snippet}")
        
        context_str = "\n\n".join(formatted_snippets)
        
        return self.semantic_understanding_template.format(
            user_input=user_input,
            context_snippets=context_str
        )
    
    def create_path_expansion_prompt(
        self,
        user_query: str,
        current_page: Dict[str, Any],
        available_relations: List[str]
    ) -> str:
        """创建路径扩展策略prompt"""
        
        # 格式化当前页面信息
        page_info = f"""
- 页面ID: {current_page.get('page_id', 'unknown')}
- 标题: {current_page.get('title', 'Unknown')}
- 标签: {', '.join(current_page.get('tags', []))}
- 内容摘要: {current_page.get('summary', 'No summary available')[:200]}...
"""
        
        # 格式化可用关系
        relations_str = ", ".join(available_relations)
        
        return self.path_expansion_template.format(
            user_query=user_query,
            current_page=page_info,
            available_relations=relations_str
        )


# 预定义的常用prompt实例
intent_prompt = IntentEvaluationPrompt()


# 便利函数
def get_confidence_evaluation_prompt(user_input: str, candidate_paths: List[Dict[str, Any]]) -> str:
    """获取置信度评估prompt的便利函数"""
    return intent_prompt.create_evaluation_prompt(user_input, candidate_paths)


def get_keyword_extraction_prompt(user_input: str) -> str:
    """获取关键词提取prompt的便利函数"""
    return intent_prompt.create_keyword_extraction_prompt(user_input)


def get_semantic_understanding_prompt(user_input: str, context_snippets: List[str]) -> str:
    """获取语义理解prompt的便利函数"""
    return intent_prompt.create_semantic_understanding_prompt(user_input, context_snippets)


# 示例使用
if __name__ == "__main__":
    # 测试prompt模板
    sample_user_input = "我想找关于机器学习项目的笔记"
    sample_paths = [
        {
            'root_page_id': 'page_001',
            'root_title': 'Deep Learning项目总结',
            'root_tags': ['机器学习', '深度学习', '项目'],
            'search_keyword': '机器学习',
            'path_type': 'semantic_match',
            'relevance_score': 0.89
        },
        {
            'root_page_id': 'page_002', 
            'root_title': 'Python编程笔记',
            'root_tags': ['编程', 'Python'],
            'search_keyword': '项目',
            'path_type': 'semantic_match',
            'relevance_score': 0.45
        }
    ]
    
    # 生成评估prompt
    evaluation_prompt = get_confidence_evaluation_prompt(sample_user_input, sample_paths)
    print("=== 置信度评估Prompt ===")
    print(evaluation_prompt)
    
    print("\n" + "="*50 + "\n")
    
    # 生成关键词提取prompt
    keyword_prompt = get_keyword_extraction_prompt(sample_user_input)
    print("=== 关键词提取Prompt ===")
    print(keyword_prompt)