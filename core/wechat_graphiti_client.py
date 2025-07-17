"""
微信关系图谱 - Graphiti客户端
基于Graphiti-core的微信Episode存储和搜索
"""

import asyncio
import json
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pathlib import Path

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.utils.bulk_utils import RawEpisode
# Using default clients for now
from loguru import logger
import google.generativeai as genai

from core.wechat_models import WeChatEpisode, EpisodeGenerationResult
from config.settings import settings
from graphiti_core.llm_client.gemini_client import GeminiClient, LLMConfig
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient

class WeChatGraphitiClient:
    """微信关系图谱 - Graphiti客户端"""
    
    def __init__(self):
        self.graphiti: Optional[Graphiti] = None
        self._initialized = False
        
    async def initialize(self):
        """初始化Graphiti客户端"""
        if self._initialized:
            return
            
        try:
            # 配置Gemini
            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            # 使用简化的初始化方法
            self.graphiti = Graphiti(
                uri=settings.neo4j_uri,
                user=settings.neo4j_username,
                password=settings.neo4j_password,
            llm_client=GeminiClient(
                config=LLMConfig(
                    api_key=settings.GEMINI_API_KEY,
                    model=settings.GEMINI_MODEL
                )
            ),
            embedder=GeminiEmbedder(
                config=GeminiEmbedderConfig(
                    api_key=settings.GEMINI_API_KEY,
                    embedding_model="embedding-001"
                )
            ),
            cross_encoder=GeminiRerankerClient(
                config=LLMConfig(
                    api_key=settings.GEMINI_API_KEY,
                    model="gemini-2.5-flash-lite-preview-06-17"
                )
            )
        )
            
            await self.graphiti.build_indices_and_constraints()
            self._initialized = True
            logger.info("WeChat Graphiti客户端初始化成功")
            
        except Exception as e:
            logger.error(f"WeChat Graphiti客户端初始化失败: {e}")
            raise
    
    async def close(self):
        """关闭Graphiti客户端"""
        if self.graphiti and self._initialized:
            await self.graphiti.close()
            self._initialized = False
            logger.info("WeChat Graphiti客户端已关闭")

    
    async def add_graphiti_episodes_bulk(self, episodes: List[Dict[str, Any]]) -> EpisodeGenerationResult:
        """
        批量添加Graphiti Episodes到图数据库（使用单个添加以获得更好的错误信息）
        
        Args:
            episodes: Graphiti Episode字典列表
            
        Returns:
            EpisodeGenerationResult: 批量添加结果
        """
        if not self._initialized:
            await self.initialize()
            
        successful_episodes = 0
        errors = []
        
        try:
            # 逐个添加Episode以获得更好的错误信息
            for i, episode in enumerate(episodes):
                try:
                    # 直接使用Graphiti Episode格式
                    await self.graphiti.add_episode(
                        name=episode.get("name", ""),
                        episode_body=episode.get("episode_body", ""),
                        source_description=episode.get("source_description", ""),
                        reference_time=episode.get("reference_time", datetime.now()),
                        source=EpisodeType.text,
                        group_id="wechat_relationships"
                    )
                    
                    successful_episodes += 1
                    
                    # 每处理50个输出一次进度
                    if (i + 1) % 50 == 0:
                        logger.info(f"已处理 {i + 1}/{len(episodes)} 个Episode")
                        
                except Exception as e:
                    error_msg = f"添加Episode失败 (第{i+1}个): {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    
                    # 如果连续失败太多次，停止处理
                    if len(errors) > 10:
                        logger.error("连续失败过多，停止处理")
                        break
            
            logger.info(f"成功添加 {successful_episodes} 个Episode，失败 {len(errors)} 个")
            return EpisodeGenerationResult(
                success=len(errors) == 0,
                total_episodes=successful_episodes,
                episodes_by_type=self._count_graphiti_episodes_by_type(episodes) if successful_episodes > 0 else {},
                errors=errors
            )
            
        except Exception as e:
            logger.error(f"批量添加Episodes失败: {e}")
            return EpisodeGenerationResult(
                success=False,
                total_episodes=successful_episodes,
                errors=[str(e)] + errors
            )
    
    async def search_episodes(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        搜索Episodes
        
        Args:
            query: 搜索查询
            limit: 结果限制
            
        Returns:
            List[Dict[str, Any]]: 搜索结果
        """
        if not self._initialized:
            await self.initialize()
            
        try:
            # 使用Graphiti搜索
            search_results = await self.graphiti.search(
                query=query,
                num_results=limit,
                group_ids=["wechat_relationships"]
            )
            
            # 转换搜索结果格式
            formatted_results = []
            for result in search_results:
                formatted_results.append({
                    'id': getattr(result, 'uuid', str(result)),
                    'fact': getattr(result, 'fact', str(result)),
                    'source_node_uuid': getattr(result, 'source_node_uuid', None),
                    'target_node_uuid': getattr(result, 'target_node_uuid', None),
                    'score': getattr(result, 'score', 0.0)
                })
            
            logger.debug(f"搜索查询 '{query}' 找到 {len(formatted_results)} 个结果")
            return formatted_results
            
        except Exception as e:
            logger.error(f"搜索Episodes失败: {e}")
            return []
    
    async def get_graph_stats(self) -> Dict[str, Any]:
        """获取图数据库统计信息"""
        if not self._initialized:
            await self.initialize()
            
        try:
            # 获取基本统计信息
            stats = {
                "total_episodes": 0,
                "total_entities": 0,
                "total_relationships": 0,
                "group_id": "wechat_relationships",
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            # 这里可以添加更多统计查询
            logger.debug("获取图数据库统计信息")
            return stats
            
        except Exception as e:
            logger.error(f"获取图数据库统计信息失败: {e}")
            return {"error": str(e)}
    
    def _convert_to_raw_episode(self, episode: WeChatEpisode) -> RawEpisode:
        """
        将WeChatEpisode转换为Graphiti RawEpisode格式
        
        Args:
            episode: 微信Episode对象
            
        Returns:
            RawEpisode: Graphiti原始Episode格式
        """
        import uuid
        
        return RawEpisode(
            name=f"WeChat_{episode.episode_type.value}_{episode.episode_id}",
            uuid=str(uuid.uuid4()),  # 使用随机UUID
            content=episode.content,
            source_description=f"WeChat {episode.episode_type.value} from {episode.source_file}",
            source=EpisodeType.text,  # 使用text类型
            reference_time=episode.created_at
        )
    
    def _count_graphiti_episodes_by_type(self, episodes: List[Dict[str, Any]]) -> Dict[str, int]:
        """按类型统计Graphiti Episode数量 - 返回简单的字符串键值对"""
        from core.wechat_models import EpisodeType
        
        counts = {}
        type_mapping = {
            "Person": EpisodeType.PERSON_IDENTITY.value,
            "Community": EpisodeType.GROUP_CONTEXT.value,
            "Context": EpisodeType.GROUP_CONTEXT.value,
            "Relationship": EpisodeType.PERSON_RELATIONSHIP.value,
            "Membership": EpisodeType.GROUP_MEMBERSHIP.value,
            "Activity": EpisodeType.ACTIVITY_PARTICIPATION.value,
            "Social Network": EpisodeType.SOCIAL_SCENARIO.value
        }
        
        for episode in episodes:
            # 从name中提取类型
            name = episode.get("name", "")
            episode_type = name.split(":")[0] if ":" in name else "Unknown"
            
            # 映射到标准类型
            mapped_type = type_mapping.get(episode_type, "unknown")
            counts[mapped_type] = counts.get(mapped_type, 0) + 1
            
        return counts
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            if not self._initialized:
                await self.initialize()
            return True
        except Exception as e:
            logger.error(f"健康检查失败: {e}")
            return False
    
    async def clear_wechat_data(self) -> bool:
        """清除所有微信数据（谨慎使用）"""
        if not self._initialized:
            await self.initialize()
            
        try:
            # 这里可以添加清除特定group_id的数据的逻辑
            logger.warning("清除微信数据功能需要实现")
            return True
        except Exception as e:
            logger.error(f"清除微信数据失败: {e}")
            return False