

"""
关系搜索 - 使用 Graphiti 进行关系查询
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
    """关系搜索器"""

    def __init__(self):
        self.client = WeChatGraphitiClient(use_2_0_flash=True)  # 使用gemini-2.0-flash
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
        搜索微信关系 - Entity-first架构
        
        两步法：1) 使用高级搜索定位最匹配的Entity 2) 获取该Entity的所有关系

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            RelationshipSearchResult: 搜索结果
        """
        start_time = time.time()

        try:
            logger.info(f"开始关系搜索: {query}")

            # 第一步: 使用Graphiti高级搜索定位最匹配的Entity节点
            matched_entities = await self._search_entities_with_graphiti(query, max_results)
            
            if not matched_entities:
                logger.warning(f"未找到匹配的Entity: {query}")
                return RelationshipSearchResult(
                    success=False,
                    error=f"未找到匹配的实体: {query}",
                    processing_time_ms=int((time.time() - start_time) * 1000)
                )

            # 第二步: 基于匹配的Entity进行关系搜索
            all_results = []
            
            for entity in matched_entities:
                entity_uuid = entity.get('uuid', '')
                entity_name = entity.get('name', '')
                
                logger.info(f"为实体 '{entity_name}' ({entity_uuid}) 搜索关系")
                
                # 获取该实体的关系信息
                entity_relationships = await self._get_entity_relationships(entity_uuid)
                
                # 将实体信息添加到结果中
                # 处理Neo4j DateTime类型
                created_at = entity.get('created_at', '')
                if created_at and hasattr(created_at, 'isoformat'):
                    created_at = created_at.isoformat()
                elif created_at:
                    created_at = str(created_at)
                
                entity_result = {
                    'type': 'node',
                    'uuid': entity_uuid,
                    'name': entity_name,
                    'summary': entity.get('summary', ''),
                    'labels': entity.get('labels', []),
                    'attributes': entity.get('attributes', {}),
                    'created_at': created_at,
                    'score': entity.get('score', 0),
                    'relationships': entity_relationships  # 附加关系信息
                }
                all_results.append(entity_result)

            # 第三步: 排序和格式化结果
            sorted_results = sorted(all_results, key=lambda x: x.get('score', 0), reverse=True)
            final_results = sorted_results[:max_results]

            logger.info(f"最终找到 {len(final_results)} 个实体和关系")

            # 格式化答案
            formatted_answer = await self._format_entity_based_answer(final_results, query)

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


    async def _search_entities_with_graphiti(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        使用Graphiti高级搜索定位Entity节点
        
        Args:
            query: 搜索查询
            max_results: 最大结果数
            
        Returns:
            List[Dict[str, Any]]: 匹配的Entity列表
        """
        try:
            # 使用Graphiti的高级搜索配置 - 基于官方MCP实现
            from graphiti_core.search.search_config_recipes import NODE_HYBRID_SEARCH_RRF
            from graphiti_core.search.search_filters import SearchFilters
            
            # 配置搜索过滤器，只搜索Entity节点
            search_filter = SearchFilters(
                node_labels=["Entity"]
            )
            
            # 使用高级搜索配置
            search_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
            search_config.limit = max_results * 2  # 搜索更多结果用于筛选
            
            # 执行高级搜索 - 基于官方MCP的search_方法
            # 同时搜索微信关系和个人记忆两个group_id
            search_results = await self.client.graphiti.search_(
                query=query,
                config=search_config,
                group_ids=["wechat_relationships", "personal_memories"],
                search_filter=search_filter
            )
            
            if not search_results.nodes:
                logger.warning(f"Graphiti高级搜索未找到Entity节点: {query}")
                return []
            
            # 格式化节点结果 - 基于官方MCP的格式化方法
            formatted_entities = []
            
            for node in search_results.nodes:
                try:
                    # 使用官方的格式化方法
                    entity_dict = {
                        'uuid': node.uuid,
                        'name': node.name,
                        'summary': node.summary if hasattr(node, 'summary') else '',
                        'labels': node.labels if hasattr(node, 'labels') else [],
                        'group_id': node.group_id,
                        'created_at': node.created_at.isoformat() if hasattr(node.created_at, 'isoformat') else str(node.created_at),
                        'attributes': node.attributes if hasattr(node, 'attributes') else {},
                    }
                    
                    # 计算匹配得分
                    entity_dict['score'] = self._calculate_entity_match_score(entity_dict, query)
                    formatted_entities.append(entity_dict)
                    
                except Exception as e:
                    logger.warning(f"格式化节点失败: {e}")
                    continue
            
            # 按得分排序
            sorted_entities = sorted(formatted_entities, key=lambda x: x.get('score', 0), reverse=True)

            # 过滤掉低分实体 - 最低分数阈值为1.0
            MIN_SCORE_THRESHOLD = 1.0
            filtered_entities = [e for e in sorted_entities if e.get('score', 0) >= MIN_SCORE_THRESHOLD]

            logger.info(f"Graphiti搜索找到 {len(sorted_entities)} 个匹配的Entity，过滤后保留 {len(filtered_entities)} 个")
            for i, entity in enumerate(filtered_entities[:5]):
                logger.info(f"Entity {i+1}: {entity.get('name', 'N/A')} (score: {entity.get('score', 0):.2f})")

            return filtered_entities[:max_results]
            
        except Exception as e:
            logger.error(f"Graphiti Entity搜索失败: {e}")
            return []


    async def _get_entity_by_uuid(self, entity_uuid: str) -> Optional[Dict[str, Any]]:
        """
        根据UUID获取Entity节点信息
        
        Args:
            entity_uuid: 实体UUID
            
        Returns:
            Optional[Dict[str, Any]]: 实体信息
        """
        if not self._neo4j_driver:
            return None
            
        try:
            async with self._neo4j_driver.session() as session:
                query = """
                MATCH (e:Entity {uuid: $uuid})
                RETURN e.uuid as uuid,
                       e.name as name,
                       e.summary as summary,
                       e.labels as labels,
                       e.created_at as created_at
                """
                
                result = await session.run(query, uuid=entity_uuid)
                record = await result.single()
                
                if record:
                    # 处理Neo4j DateTime类型
                    created_at = record.get('created_at', '')
                    if created_at and hasattr(created_at, 'isoformat'):
                        created_at = created_at.isoformat()
                    elif created_at:
                        created_at = str(created_at)
                    
                    return {
                        'uuid': record.get('uuid', ''),
                        'name': record.get('name', ''),
                        'summary': record.get('summary', ''),
                        'labels': record.get('labels', []),
                        'attributes': {},  # 数据库中没有此字段
                        'created_at': created_at
                    }
                    
        except Exception as e:
            logger.error(f"获取Entity {entity_uuid} 失败: {e}")
            
        return None

    async def _get_entity_relationships(self, entity_uuid: str) -> List[Dict[str, Any]]:
        """
        第二步：获取Entity的关系信息（去重版本）

        Args:
            entity_uuid: 实体UUID

        Returns:
            List[Dict[str, Any]]: 去重后的关系信息列表
        """
        if not self._neo4j_driver:
            return []

        try:
            async with self._neo4j_driver.session() as session:
                # 查询与该实体相关的所有关系和连接的其他实体
                query = """
                MATCH (e:Entity {uuid: $uuid})-[r:RELATES_TO|MENTIONS]-(other:Entity)
                RETURN r.fact as fact,
                       other.uuid as other_uuid,
                       other.name as other_name,
                       other.summary as other_summary,
                       type(r) as relationship_type
                LIMIT 20
                """

                result = await session.run(query, uuid=entity_uuid)

                relationships = []
                seen_uuids = set()  # 用于去重：只保留每个other_uuid的第一个关系

                async for record in result:
                    other_uuid = record.get('other_uuid', '')

                    # 如果这个UUID已经处理过，跳过（保留第一个关系描述）
                    if other_uuid in seen_uuids:
                        continue

                    seen_uuids.add(other_uuid)

                    fact = record.get('fact', '')

                    relationship = {
                        'fact': fact,
                        'relationship_type': record.get('relationship_type', ''),
                        'other_entity': {
                            'uuid': other_uuid,
                            'name': record.get('other_name', ''),
                            'summary': record.get('other_summary', '')
                        }
                    }
                    relationships.append(relationship)

                logger.info(f"为Entity {entity_uuid} 找到 {len(relationships)} 个关系（去重后）")
                return relationships

        except Exception as e:
            logger.error(f"获取Entity关系失败: {e}")
            return []

    def _calculate_entity_match_score(self, entity: Dict[str, Any], query: str) -> float:
        """
        计算实体与查询的匹配得分 - 优化版本
        
        Args:
            entity: 实体信息
            query: 查询字符串
            
        Returns:
            float: 匹配得分
        """
        score = 0.0
        query_lower = query.lower()
        name = entity.get('name', '').lower()
        
        if not name:
            return score
        
        # 1. 完全匹配 (最高优先级)
        if query_lower == name:
            score += 15.0
            
        # 2. 前缀匹配 (高优先级，适合部分匹配查询)
        elif name.startswith(query_lower):
            # 根据查询长度和名称长度调整权重
            prefix_ratio = len(query_lower) / len(name)
            if prefix_ratio >= 0.5:  # 查询占名称50%以上
                score += 12.0
            elif prefix_ratio >= 0.3:  # 查询占名称30%以上
                score += 8.0
            else:  # 查询占名称30%以下，权重降低
                score += 4.0
                
        # 3. 包含匹配 (中等优先级)
        elif query_lower in name:
            # 查询在名称中的位置越靠前，得分越高
            position = name.find(query_lower)
            position_weight = max(0, 5.0 - position * 0.5)  # 位置权重递减
            length_ratio = len(query_lower) / len(name)
            score += position_weight + length_ratio * 3.0
            
        # 4. 词级匹配 (处理空格分隔的词)
        elif ' ' in name or ' ' in query_lower:
            query_words = set(query_lower.split())
            name_words = set(name.split())
            matched_words = query_words & name_words
            if matched_words:
                match_ratio = len(matched_words) / max(len(query_words), len(name_words))
                score += 3.0 + match_ratio * 4.0
                
        # 5. 字符级匹配 (处理连续字符，如中文名)
        else:
            # 计算最长公共子序列
            common_chars = self._calculate_common_substring_ratio(query_lower, name)
            if common_chars > 0.3:  # 至少30%相似度
                score += common_chars * 3.0
        
        # 6. 特殊模式匹配
        # 特殊处理："肥猫" 应该匹配 "ゞ肥の猫ゞ"
        if "肥" in query_lower and "猫" in query_lower:
            if "肥" in name and "猫" in name:
                score += 10.0  # 高权重匹配
                
        # 特殊处理：英文缩写 (如 "J" 匹配 "JZX")
        if len(query_lower) == 1 and query_lower.isalpha():
            if name.startswith(query_lower.upper()) or name.startswith(query_lower):
                # 单字母查询的匹配度需要很高的名称相似度
                score += 6.0
        
        # 7. 摘要匹配 (提高权重 - 因为Graphiti的语义搜索已经很好)
        summary = entity.get('summary', '').lower()
        if summary and query_lower in summary:
            # 查询词在摘要中出现，说明语义相关性高
            score += 3.0

            # 如果摘要开头就提到查询词，权重更高
            if summary.startswith(query_lower):
                score += 2.0

        # 8. 属性匹配 (中等权重)
        attributes = entity.get('attributes', {})
        if attributes:
            for key, value in attributes.items():
                if query_lower in str(value).lower():
                    score += 1.5
                    break

        # 9. 如果到这里分数还是0，说明完全不相关
        # 但如果Entity名称很短（1-2个字），给一个基础分避免误伤
        if score == 0 and len(name) <= 2:
            score = 0.5

        return score
    
    def _calculate_common_substring_ratio(self, str1: str, str2: str) -> float:
        """计算两个字符串的最长公共子序列比例"""
        if not str1 or not str2:
            return 0.0
            
        # 动态规划计算最长公共子序列
        m, n = len(str1), len(str2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if str1[i-1] == str2[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])
        
        # 返回相对于较短字符串的比例
        lcs_length = dp[m][n]
        return lcs_length / min(m, n)

    async def _format_entity_based_answer(self, results: List[Dict[str, Any]], query: str) -> str:
        """
        基于实体的答案格式化
        
        Args:
            results: 搜索结果
            query: 原始查询
            
        Returns:
            str: 格式化的答案
        """
        if not results:
            return f"未找到与 '{query}' 相关的关系信息。"

        answer_parts = []
        
        for i, entity in enumerate(results, 1):
            entity_name = entity.get('name', '未知')
            entity_summary = entity.get('summary', '')
            relationships = entity.get('relationships', [])
            
            # 实体基本信息
            answer_parts.append(f"{i}. {entity_name} (匹配得分: {entity.get('score', 0):.1f})")
            if entity_summary:
                answer_parts.append(f"   摘要: {entity_summary[:200]}{'...' if len(entity_summary) > 200 else ''}")
            
            # 关系信息
            if relationships:
                answer_parts.append(f"   相关关系 ({len(relationships)}个):")
                for j, rel in enumerate(relationships[:5], 1):  # 只显示前5个关系
                    fact = rel.get('fact', '')
                    other_entity = rel.get('other_entity', {})
                    other_name = other_entity.get('name', '未知')
                    
                    if fact:
                        answer_parts.append(f"     {j}. {fact}")
                    else:
                        answer_parts.append(f"     {j}. 与 {other_name} 存在关系")
            else:
                answer_parts.append("   未找到相关关系")
            
            answer_parts.append("")  # 空行分隔
        
        return "\n".join(answer_parts)


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
