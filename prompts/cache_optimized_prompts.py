"""
KV Cache优化的Deep Research提示词系统
使用稳定前缀 + 追加式设计来最大化KV cache hit rate
"""

from langchain.prompts import PromptTemplate
from typing import List, Dict, Any
import json
from core.models import RESEARCH_COMPLEXITY_CONFIGS


class CacheOptimizedPrompts:
    """KV Cache优化的提示词设计"""
    
    # 稳定的系统前缀（永不变化，最大化cache hit）
    STABLE_SYSTEM_PREFIX = """你是一位资深的学术研究助手和内容分析专家。你的任务是进行高质量的知识内容分析和研究综合。

核心能力：
1. 结构化内容分析
2. 逻辑关系梳理  
3. 核心价值提炼
4. 学术级综合
5. 证据链构建

分析原则：
- 保持逻辑严密性
- 突出核心价值
- 确保可操作性
- 维护学术规范
- 支持后续研究

输出要求：
- 严格遵循JSON schema
- 保持结构完整性
- 确保内容质量
- 支持可追溯性

现在开始执行具体的分析任务："""

    # 复杂度特定的中间层（相对稳定）
    COMPLEXITY_TEMPLATES = {
        "overview": """
**分析模式：高层概览**
目标：生成执行级摘要，突出核心结论和主要趋势
重点：关键发现、战略洞察、趋势判断
风格：简洁明了、高度概括、决策导向
压缩策略：保留30%核心信息，突出结论性内容
摘要长度：800字符左右
""",
        "standard": """
**分析模式：标准分析** 
目标：平衡深度与广度，提供实用的研究参考
重点：核心观点、支撑证据、实践建议
风格：结构清晰、论证完整、应用导向
压缩策略：保留50%信息，平衡理论与实践
摘要长度：1200字符左右
""",
        "detailed": """
**分析模式：深度分析**
目标：深入探讨理论与实践，提供全面的研究基础
重点：理论框架、方法论、案例分析、实践应用
风格：学术严谨、逻辑完整、研究导向
压缩策略：保留60%信息，强调方法论完整性
摘要长度：1800字符左右
""",
        "comprehensive": """
**分析模式：全面研究**
目标：学术级深度分析，构建完整的知识体系
重点：理论框架、文献脉络、方法论、实证分析、创新贡献
风格：学术规范、体系完整、创新导向
压缩策略：保留80%信息，维护完整理论体系
摘要长度：2500字符左右
"""
    }

    def __init__(self):
        """初始化提示词模板"""
        self.page_analysis_template = PromptTemplate(
            input_variables=["complexity", "page_title", "page_content"],
            template=self._create_page_analysis_template()
        )
        
        self.clustering_template = PromptTemplate(
            input_variables=["complexity", "page_metadata", "target_clusters"],
            template=self._create_clustering_template()
        )
        
        self.synthesis_template = PromptTemplate(
            input_variables=["complexity", "cluster_results", "target_pages"],
            template=self._create_synthesis_template()
        )


    """
    暂未使用
    """

    def _create_page_analysis_template(self) -> str:
        """创建页面分析模板（稳定前缀 + 动态内容）"""
        return f"""{self.STABLE_SYSTEM_PREFIX}

{{complexity_template}}

{{purpose_section}}

**当前任务**：单页面结构化分析

**输入信息**：
页面标题：{{page_title}}
页面内容：
{{page_content}}

**分析要求**：
根据上述分析模式，按以下JSON schema输出：

```json
{{
    "page_analysis": {{
        "notion_id": "页面ID",
        "title": "{{page_title}}",
        "content": "原始内容（保持不变）",
        "summary": "根据当前分析模式生成的核心摘要",
        "key_points": [
            "要点1：具体且可操作的核心观点",
            "要点2：包含关键数据或结论", 
            "要点3：重要的方法论或框架",
            "要点4：值得引用的核心洞察",
            "要点5：实用的建议或指导"
        ],
        "importance_score": 0.85,
        "relevance_score": 0.90,
        "word_count": 实际字数,
        "supporting_quotes": [
            "原文中最有价值的直接引用1",
            "支撑核心论点的关键句子2"
        ],
        "research_value": {{
            "theoretical_contribution": "理论贡献度描述",
            "practical_application": "实用性价值说明", 
            "citation_worthiness": "引用价值评估"
        }}
    }}
}}
```

**质量标准**：
- 摘要必须能让读者快速掌握核心内容
- 要点必须具体、可验证、有操作价值
- 重要性评分基于学术价值、实用性、稀缺性
- 关联度评分基于与研究目的的匹配程度
- 引用必须是原文中最精华的表述

请开始分析："""

    def _create_clustering_template(self) -> str:
        """创建语义分簇模板"""
        return f"""{self.STABLE_SYSTEM_PREFIX}

{{complexity_template}}

**当前任务**：语义分簇与主题识别

**输入信息**：
页面元数据列表：
{{page_metadata}}

目标簇数量：{{target_clusters}}

**分簇要求**：
根据页面标题、标签和路径信息进行语义分簇，确保：
1. 主题相关性：同簇页面具有相似主题
2. 负载均衡：各簇页面数量相对均衡
3. 逻辑连贯：簇内页面逻辑相关

按以下JSON schema输出：

```json
{{
    "clustering_result": {{
        "clusters": [
            {{
                "cluster_id": "cluster_1",
                "theme": "主题名称",
                "description": "主题描述",
                "page_ids": ["page_id_1", "page_id_2", "page_id_3"],
                "rationale": "分簇理由"
            }}
        ],
        "cluster_count": {{target_clusters}},
        "distribution_summary": "分布总结"
    }}
}}
```

请开始分簇："""

    def _create_synthesis_template(self) -> str:
        """创建研究综合模板"""
        return f"""{self.STABLE_SYSTEM_PREFIX}

{{complexity_template}}

**当前任务**：多簇综合分析与研究上下文生成

**输入数据**：
各簇分析结果：
{{cluster_results}}

目标页面数：{{target_pages}}

**综合要求**：
基于当前分析模式，生成结构化研究上下文：

```json
{{
    "research_context": {{
        "executive_summary": "基于当前分析模式的综合摘要，符合目标长度要求",
        
        "topic_clusters": [
            {{
                "cluster_id": "cluster_1",
                "theme": "主题名称",
                "cluster_synthesis": "400-600字主题综合分析",
                "representative_quotes": [
                    "该主题最有代表性的直接引用1",
                    "支撑核心观点的关键引用2"
                ],
                "cross_references": ["与其他主题的关联说明"]
            }}
        ],
        
        "top_pages": [
            {{
                "notion_id": "页面ID",
                "title": "页面标题",
                "summary": "页面摘要",
                "importance_score": 0.95,
                "selection_reason": "入选理由"
            }}
        ],
        
        "key_insights": [
            "洞察1：跨主题的重要发现或趋势",
            "洞察2：具有指导意义的核心原则", 
            "洞察3：值得深入研究的问题方向",
            "洞察4：实践中的关键启示",
            "洞察5：理论与实践的重要联系"
        ],
        
        "supporting_evidence": [
            {{
                "evidence_type": "数据支撑|案例研究|理论依据|实证发现",
                "description": "证据具体描述",
                "source_reference": "来源页面标题",
                "reliability_score": 0.9
            }}
        ],
        
        "research_framework": {{
            "problem_definition": "基于内容总结的核心研究问题",
            "theoretical_foundation": "理论基础和概念框架",
            "methodology_insights": "从内容中提炼的方法论指导",
            "expected_contributions": "可能的学术和实践贡献"
        }},
        
        "future_directions": [
            "基于当前研究内容提出的后续研究方向1",
            "需要进一步探索的关键问题2", 
            "值得深入的实践应用领域3"
        ]
    }}
}}
```

**质量检查清单**：
✓ 执行摘要能否让读者快速理解整个研究领域？
✓ 主题分析是否提供了新的见解或整合？
✓ 关键洞察是否具有指导后续研究的价值？
✓ 支撑证据是否足够可信和相关？
✓ 整体结构是否便于大模型理解和应用？

请开始综合分析："""

    def create_page_analysis_prompt(self, complexity: str, page_content: str, page_title: str, research_purpose: str = "") -> str:
        """创建页面分析prompt（前缀稳定 + 内容追加）"""
        
        complexity_template = self.COMPLEXITY_TEMPLATES[complexity]
        
        # 添加研究目的信息
        purpose_section = ""
        if research_purpose:
            purpose_section = f"""
**研究目的**：{research_purpose}

**关联度评估要求**：
请特别评估页面内容与上述研究目的的关联程度：
- 1.0: 高度相关，直接回答研究问题
- 0.8: 强相关，提供重要支撑信息
- 0.6: 中等相关，有一定参考价值
- 0.4: 弱相关，边缘性参考信息
- 0.2: 低相关，几乎无关联
- 0.0: 完全无关，应当过滤

"""
        
        return self.page_analysis_template.format(
            complexity_template=complexity_template,
            purpose_section=purpose_section,
            page_title=page_title,
            page_content=page_content
        )

    def create_clustering_prompt(self, complexity: str, page_metadata: List[Dict], target_clusters: int) -> str:
        """创建语义分簇prompt"""
        
        complexity_template = self.COMPLEXITY_TEMPLATES[complexity]
        
        # 格式化页面元数据
        formatted_metadata = []
        for i, page in enumerate(page_metadata):
            metadata_str = f"""{i}. "{page.get('title', 'Unknown')}"
   - ID: {page.get('notion_id', 'unknown')}
   - 标签: {', '.join(page.get('tags', []))}
   - 路径: {page.get('path_string', 'N/A')}"""
            formatted_metadata.append(metadata_str)
        
        metadata_str = "\n".join(formatted_metadata)
        
        return self.clustering_template.format(
            complexity_template=complexity_template,
            page_metadata=metadata_str,
            target_clusters=target_clusters
        )

    def create_synthesis_prompt(self, complexity: str, cluster_results: List[Dict], target_pages: int) -> str:
        """创建综合分析prompt（前缀稳定 + 结果追加）"""
        
        complexity_template = self.COMPLEXITY_TEMPLATES[complexity]
        
        return self.synthesis_template.format(
            complexity_template=complexity_template,
            cluster_results=json.dumps(cluster_results, ensure_ascii=False, indent=2),
            target_pages=target_pages
        )



# 预定义实例
cache_optimized_prompts = CacheOptimizedPrompts()


# 便利函数
def get_page_analysis_prompt(complexity: str, page_content: str, page_title: str, research_purpose: str = "") -> str:
    """获取页面分析prompt的便利函数"""
    return cache_optimized_prompts.create_page_analysis_prompt(complexity, page_content, page_title, research_purpose)


def get_clustering_prompt(complexity: str, page_metadata: List[Dict], target_clusters: int) -> str:
    """获取语义分簇prompt的便利函数"""
    return cache_optimized_prompts.create_clustering_prompt(complexity, page_metadata, target_clusters)


def get_synthesis_prompt(complexity: str, cluster_results: List[Dict], target_pages: int) -> str:
    """获取综合分析prompt的便利函数"""
    return cache_optimized_prompts.create_synthesis_prompt(complexity, cluster_results, target_pages)




# 示例使用
if __name__ == "__main__":
    # 测试prompt生成
    sample_content = "这是一个示例页面内容，包含重要的技术信息和分析..."
    sample_title = "深度学习项目总结"
    
    # 生成不同复杂度的prompt
    for complexity in ["overview", "standard", "detailed", "comprehensive"]:
        print(f"\n=== {complexity.upper()} 模式 ===")
        prompt = get_page_analysis_prompt(complexity, sample_content, sample_title)
        print(f"Prompt长度: {len(prompt)} 字符")
        print(f"前缀稳定性: {'是' if prompt.startswith(CacheOptimizedPrompts.STABLE_SYSTEM_PREFIX) else '否'}")