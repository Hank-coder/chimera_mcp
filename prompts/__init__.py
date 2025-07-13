"""
Prompts模块
统一管理所有LLM交互的提示词模板，使用LangChain的PromptTemplate
"""

from .intent_evaluation import (
    IntentEvaluationPrompt,
    intent_prompt,
    get_confidence_evaluation_prompt,
    get_keyword_extraction_prompt,
    get_semantic_understanding_prompt
)

__all__ = [
    'IntentEvaluationPrompt',
    'intent_prompt',
    'get_confidence_evaluation_prompt',
    'get_keyword_extraction_prompt',
    'get_semantic_understanding_prompt'
]