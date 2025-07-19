

"""
微信关系搜索 - 使用 Graphiti 进行关系查询
基于 Graphiti 的 search_ 方法实现简单高效的关系搜索

数据库结构:
- 节点标签: Entity, Episodic
- 边类型: RELATES_TO, MENTIONS
- Entity 节点包含微信联系人、群组等信息
- Episodic 节点包含聊天记录等信息
"""

import asyncio
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

from graphiti_core.search.search_config_recipes import (
    NODE_HYBRID_SEARCH_EPISODE_MENTIONS,
    NODE_HYBRID_SEARCH_RRF,
    NODE_HYBRID_SEARCH_CROSS_ENCODER,
    COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
    EDGE_HYBRID_SEARCH_RRF
)
from graphiti_core.search.search_filters import SearchFilters
from loguru import logger
from core.wechat_graphiti_client import WeChatGraphitiClient
from core.wechat_models import QueryAnalysisResult
from neo4j import AsyncGraphDatabase
from config.settings import settings


@dataclass
class RelationshipSearchResult:
    """关系搜索结果"""
    success: bool
    query_analysis: Optional[QueryAnalysisResult] = None
    episodes: List[Dict[str, Any]] = None
    results: List[Dict[str, Any]] = None  # 添加results字段以保持兼容性
    formatted_answer: str = ""
    error: str = ""
    processing_time_ms: int = 0


class WeChatRelationshipSearcher:
    """微信关系搜索器"""

    def __init__(self):
        self.client = WeChatGraphitiClient()
        self._neo4j_driver = None
        self._initialized = False

    async def initialize(self):
        """初始化搜索器"""
        if not self._initialized:
            await self.client.initialize()
            # 初始化Neo4j driver
            self._neo4j_driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password)
            )
            self._initialized = True

    async def close(self):
        """关闭搜索器"""
        if self._initialized:
            await self.client.close()
            if self._neo4j_driver:
                await self._neo4j_driver.close()
            self._initialized = False

    async def search_relationships(
            self,
            query: str,
            max_results: int = 5,
    ) -> RelationshipSearchResult:
        """
        搜索微信关系

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            RelationshipSearchResult: 搜索结果
        """
        start_time = time.time()

        try:
            logger.info(f"开始关系搜索: {query}")

            # 创建搜索过滤器，根据实际数据库结构调整
            # 数据库只有 Entity 和 Episodic 标签
            search_filter = SearchFilters(
                node_labels=["Entity"],  # 只搜索 Entity 节点
            )

            all_results = []

            # 1. 使用多种搜索策略进行综合搜索
            search_configs = {
                "node_cross_encoder": NODE_HYBRID_SEARCH_CROSS_ENCODER,
                "node_rrf": NODE_HYBRID_SEARCH_RRF,
                "combined_search": COMBINED_HYBRID_SEARCH_CROSS_ENCODER
            }

            for config_name, config in search_configs.items():
                try:
                    logger.info(f"使用 {config_name} 配置进行搜索")

                    # 复制配置并设置限制
                    config_copy = config.model_copy(deep=True)
                    config_copy.limit = max_results * 2  # 获取更多结果用于后续筛选

                    # 使用高级搜索方法
                    search_results = await self.client.graphiti.search_(
                        query=query,
                        config=config_copy,
                        search_filter=search_filter
                    )

                    logger.info(
                        f"{config_name} 找到: {len(search_results.nodes)} 个节点, {len(search_results.edges)} 条边")

                    # 处理节点结果
                    for node in search_results.nodes:
                        node_dict = {
                            'type': 'node',
                            'uuid': getattr(node, 'uuid', ''),
                            'name': getattr(node, 'name', ''),
                            'summary': getattr(node, 'summary', ''),
                            'labels': getattr(node, 'labels', []),
                            'attributes': getattr(node, 'attributes', {}),
                            'created_at': getattr(node, 'created_at', ''),
                            'config_source': config_name,
                            'score': self._calculate_node_score(node, query)
                        }
                        all_results.append(node_dict)

                    # 处理边结果
                    for edge in search_results.edges:
                        edge_dict = {
                            'type': 'edge',
                            'uuid': getattr(edge, 'uuid', ''),
                            'fact': getattr(edge, 'fact', ''),
                            'source_node_uuid': getattr(edge, 'source_node_uuid', ''),
                            'target_node_uuid': getattr(edge, 'target_node_uuid', ''),
                            'relation': getattr(edge, 'relation', ''),
                            'created_at': getattr(edge, 'created_at', ''),
                            'episodes': getattr(edge, 'episodes', []),
                            'config_source': config_name,
                            'score': self._calculate_edge_score(edge, query)
                        }
                        all_results.append(edge_dict)

                except Exception as e:
                    logger.warning(f"使用 {config_name} 配置搜索失败: {e}")
                    continue

            # 2. 智能中心节点搜索
            if all_results:
                center_results = await self._perform_intelligent_center_search(
                    all_results
                )
                all_results.extend(center_results)

            # 3. 结果处理和优化
            logger.info(f"聚合前共有 {len(all_results)} 个结果")

            # 去重
            unique_results = self._deduplicate_results(all_results)

            # 智能排序
            sorted_results = self._intelligent_sort(unique_results, query)

            # 限制结果数量
            final_results = sorted_results[:max_results]

            logger.info(f"聚合后共有 {len(final_results)} 个结果")

            # 格式化答案
            formatted_answer = await self._format_answer(final_results, query)

            processing_time = int((time.time() - start_time) * 1000)

            return RelationshipSearchResult(
                success=True,
                results=final_results,
                episodes=final_results,  # 保持向后兼容
                formatted_answer=formatted_answer,
                processing_time_ms=processing_time
            )

        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            logger.error(f"关系搜索失败: {e}")

            return RelationshipSearchResult(
                success=False,
                error=str(e),
                processing_time_ms=processing_time
            )

    def _calculate_node_score(self, node, query: str) -> float:
        """计算节点得分"""
        score = 1.0
        query_lower = query.lower()
        name = getattr(node, 'name', '').lower()

        if name:
            # 完全匹配加分
            if query_lower == name:
                score += 0.5
            else:
                # 词级匹配（精确词一致），例如“张三” == “张三”
                query_words = set(query_lower.split())
                name_words = set(name.split())
                matched_words = query_words & name_words
                if matched_words:
                    score += 0.3 + 0.05 * len(matched_words)  # 基础加 0.3，命中多个词再加一点

        # 摘要匹配
        summary = getattr(node, 'summary', '').lower()
        if query_lower in summary:
            score += 0.3

        # 属性匹配
        attributes = getattr(node, 'attributes', {})
        if attributes:
            for key, value in attributes.items():
                if query_lower in str(value).lower():
                    score += 0.2
                    break

        # 标签匹配
        labels = getattr(node, 'labels', [])
        if any(query_lower in label.lower() for label in labels):
            score += 0.1

        return score

    def _calculate_edge_score(self, edge, query: str) -> float:
        """计算边得分"""
        score = 1.0
        query_lower = query.lower()

        # 事实匹配
        fact = getattr(edge, 'fact', '').lower()
        if query_lower in fact:
            score += 0.5

        # 关系类型匹配
        relation = getattr(edge, 'relation', '').lower()
        if query_lower in relation:
            score += 0.3

        # 剧集数量加权
        episodes = getattr(edge, 'episodes', [])
        if episodes:
            score += len(episodes) * 0.05

        return score

    async def _perform_intelligent_center_search(
            self,
            initial_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """智能中心节点搜索"""
        center_results = []

        # 从初始结果中选择高分节点作为中心
        node_results = [r for r in initial_results if r.get('type') == 'node']
        if not node_results:
            return center_results

        # 按得分排序，选择前几个作为中心节点
        sorted_nodes = sorted(node_results, key=lambda x: x.get('score', 0), reverse=True)
        print(sorted_nodes)

        return center_results

    async def _search_related_entities_in_neo4j(self, entity_uuid: str) -> List[Dict[str, Any]]:
        """
        在Neo4j中搜索与指定UUID相关的所有实体
        
        Args:
            entity_uuid: 实体UUID
            
        Returns:
            List[Dict[str, Any]]: 相关实体列表
        """
        if not self._neo4j_driver:
            logger.error("Neo4j driver未初始化")
            return []
            
        try:
            async with self._neo4j_driver.session() as session:
                # 查询与指定UUID直接相关的所有实体
                query = """
                MATCH (e:Entity {uuid: $uuid})-[:RELATES_TO|MENTIONS]-(related:Entity)
                RETURN DISTINCT related.uuid as uuid, 
                       related.name as name, 
                       related.summary as summary,
                       related.labels as labels
                LIMIT 20
                """
                
                result = await session.run(query, uuid=entity_uuid)
                
                related_entities = []
                async for record in result:
                    entity_dict = {
                        'uuid': record.get('uuid', ''),
                        'name': record.get('name', ''),
                        'summary': record.get('summary', ''),
                        'labels': record.get('labels', []),
                        'source': 'neo4j_related'
                    }
                    related_entities.append(entity_dict)
                    
                logger.info(f"从Neo4j中找到 {len(related_entities)} 个与UUID {entity_uuid} 相关的实体")
                return related_entities
                
        except Exception as e:
            logger.error(f"Neo4j查询失败: {e}")
            return []

    def _deduplicate_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """去重结果"""
        seen_uuids = set()
        unique_results = []

        for result in results:
            uuid = result.get('uuid', '')
            if uuid and uuid not in seen_uuids:
                seen_uuids.add(uuid)
                unique_results.append(result)

        return unique_results

    def _intelligent_sort(self, results: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """智能排序"""

        def sort_key(result):
            # 基础得分
            base_score = result.get('score', 1.0)

            # 类型权重（节点通常比边更重要）
            type_weight = 1.3 if result.get('type') == 'node' else 1.0

            # 配置来源权重
            config_source = result.get('config_source', '')
            config_weight = 1.0
            if 'cross_encoder' in config_source:
                config_weight = 1.2
            elif 'center_search' in config_source:
                config_weight = 1.1

            # 文本相似度
            text_similarity = self._calculate_text_similarity(result, query)

            return base_score * type_weight * config_weight * text_similarity

        return sorted(results, key=sort_key, reverse=True)

    def _calculate_text_similarity(self, result: Dict[str, Any], query: str) -> float:
        """计算文本相似度"""
        query_lower = query.lower()
        similarity = 1.0

        # 检查各个字段
        searchable_fields = ['name', 'fact', 'summary']

        for field in searchable_fields:
            value = result.get(field, '')
            if isinstance(value, str) and value:
                if query_lower in value.lower():
                    similarity += 0.2

        return min(similarity, 2.0)

    def _sort_by_relevance(self, results: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """按相关性排序（保持向后兼容）"""
        return self._intelligent_sort(results, query)

    async def _format_answer(self, results: List[Dict[str, Any]], query: str) -> str:
        """格式化答案，按照用户要求处理top1、top2、top3节点"""
        if not results:
            return f"未找到与 '{query}' 相关的关系信息。"

        # 分类结果
        nodes = [r for r in results if r.get('type') == 'node']
        edges = [r for r in results if r.get('type') == 'edge']

        answer_parts = []

        # 处理节点信息
        if nodes:
            # 处理top1节点：搜索所有相关实体并添加它们的summary
            if len(nodes) >= 1:
                top1_node = nodes[0]
                top1_name = top1_node.get('name', '未知')
                top1_summary = top1_node.get('summary', '')
                top1_uuid = top1_node.get('uuid', '')
                
                answer_parts.append(f"1. {top1_name} (Top1 - 主要实体)")
                if top1_summary:
                    answer_parts.append(f"   摘要: {top1_summary}")
                
                # 搜索与top1相关的所有实体
                if top1_uuid:
                    logger.info(f"搜索与top1节点 {top1_uuid} 相关的实体")
                    related_entities = await self._search_related_entities_in_neo4j(top1_uuid)
                    
                    if related_entities:
                        answer_parts.append(f"   相关实体 ({len(related_entities)}个):")
                        for j, entity in enumerate(related_entities, 1):
                            entity_summary = entity.get('summary', '')
                            entity_name = entity.get('name', '未知')
                            if entity_summary:
                                answer_parts.append(f"     {j}. {entity_name}: {entity_summary}")
                            else:
                                answer_parts.append(f"     {j}. {entity_name}")
                    else:
                        answer_parts.append("   未找到相关实体")
                
                answer_parts.append("")  # 空行分隔
            
            # 处理top2节点：只显示summary，不搜索相关实体
            if len(nodes) >= 2:
                top2_node = nodes[1]
                top2_name = top2_node.get('name', '未知')
                top2_summary = top2_node.get('summary', '')
                
                answer_parts.append(f"2. {top2_name} (Top2)")
                if top2_summary:
                    answer_parts.append(f"   摘要: {top2_summary}")
                answer_parts.append("")  # 空行分隔
            
            # 处理top3节点：只显示summary，不搜索相关实体
            if len(nodes) >= 3:
                top3_node = nodes[2]
                top3_name = top3_node.get('name', '未知')
                top3_summary = top3_node.get('summary', '')
                
                answer_parts.append(f"3. {top3_name} (Top3)")
                if top3_summary:
                    answer_parts.append(f"   摘要: {top3_summary}")
                answer_parts.append("")  # 空行分隔

        # 显示关系信息
        if edges:
            answer_parts.append("相关关系：")
            for i, edge in enumerate(edges[:3], 1):
                fact = edge.get('fact', '未知关系')
                answer_parts.append(f"{i}. {fact}")

        return "\n".join(answer_parts)

    def _identify_entity_type(self, name: str, summary: str) -> str:
        """识别实体类型"""
        name_lower = name.lower()
        summary_lower = summary.lower()

        # 检查是否是群组
        if any(keyword in name_lower for keyword in ['群', '群聊', '群组', '项目', '团队']):
            return "群组"

        # 检查是否是个人
        if any(keyword in summary_lower for keyword in ['个人', '用户', '联系人', '朋友']):
            return "个人"

        # 检查是否是组织
        if any(keyword in summary_lower for keyword in ['公司', '组织', '机构', '部门']):
            return "组织"

        return ""  # 无法识别类型


# 全局搜索器实例
_searcher: Optional[WeChatRelationshipSearcher] = None


async def search_wechat_relationships(
        query: str,
        max_results: int = 5,
) -> RelationshipSearchResult:
    """
    搜索微信关系的函数

    Args:
        query: 搜索查询
        max_results: 最大结果数
    Returns:
        RelationshipSearchResult: 搜索结果
    """
    global _searcher

    if _searcher is None:
        _searcher = WeChatRelationshipSearcher()
        await _searcher.initialize()

    return await _searcher.search_relationships(
        query=query,
        max_results=max_results,
    )


async def close_searcher():
    """关闭搜索器"""
    global _searcher
    if _searcher:
        await _searcher.close()
        _searcher = None


if __name__ == "__main__":
    # 测试搜索功能
    async def search():
        try:
            # 测试查询
            test_queries = [
                "肥猫"
            ]

            for query in test_queries:
                print(f"\n测试查询: {query}")
                result = await search_wechat_relationships(query)

                if result.success:
                    print(f"成功找到 {len(result.episodes)} 个结果")
                    print(f"格式化答案: {result.formatted_answer}")
                else:
                    print(f"搜索失败: {result.error}")

        finally:
            await close_searcher()


    asyncio.run(search())
