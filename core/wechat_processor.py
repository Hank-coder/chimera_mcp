"""
高效微信数据处理器
以Entity为中心的简化处理方案

主要功能：
1. 解析微信聊天JSON数据(entities + relationships格式)
2. 为每个Entity生成一个Episode：
   - 人员Entity：包含微信ID和所有相关关系
   - 上下文Entity：包含描述和相关参与者
3. 每个Entity的所有关系信息聚合到一个Episode中
4. 全局去重，避免重复存储
5. 批量存储到Neo4j图数据库
"""

import json
import hashlib
import asyncio
from typing import Dict, List, Any, Set, Optional
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger

from core.wechat_models import EpisodeGenerationResult
from core.wechat_graphiti_client import WeChatGraphitiClient


class WeChatDataProcessor:
    """高效微信数据处理器"""
    
    def __init__(self):
        self.client = WeChatGraphitiClient()
        self.global_episode_ids: Set[str] = set()  # 全局去重
        
    def _generate_episode_id(self, content: str) -> str:
        """生成Episode唯一ID，使用MD5哈希"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _is_duplicate_episode(self, episode_id: str) -> bool:
        """检查Episode是否重复"""
        if episode_id in self.global_episode_ids:
            return True
        self.global_episode_ids.add(episode_id)
        return False
    
    def _convert_json_to_episodes(self, json_data: Dict[str, Any], source_file: str) -> List[Dict[str, Any]]:
        """
        将JSON数据转换为Entity-centered Episode
        
        Args:
            json_data: JSON数据字典 (entities + relationships格式)
            source_file: 来源文件名
            
        Returns:
            List[Dict[str, Any]]: Graphiti Episode列表
        """
        episodes = []
        
        # 提取基础数据
        entities = json_data.get('entities', [])
        relationships = json_data.get('relationships', [])
        
        logger.debug(f"提取到 {len(entities)} 个实体, {len(relationships)} 个关系")
        
        # 为每个Entity创建一个Episode
        for entity in entities:
            episode = self._create_entity_episode(entity, relationships, source_file)
            if episode:
                episodes.append(episode)
        
        return episodes
    
    def _create_entity_episode(self, entity: Dict[str, Any], relationships: List[Dict[str, Any]], source_file: str) -> Optional[Dict[str, Any]]:
        """
        为单个Entity创建Episode
        
        Args:
            entity: Entity字典
            relationships: 所有关系列表
            source_file: 来源文件名
            
        Returns:
            Optional[Dict[str, Any]]: Episode字典
        """
        entity_name = entity.get('name', '')
        entity_type = entity.get('type', '')
        entity_id = entity.get('id', '')
        entity_desc = entity.get('description', '')
        
        if not entity_name:
            return None
        
        # 查找该Entity相关的所有关系
        related_relationships = []
        
        # 作为source的关系
        source_rels = [r for r in relationships if r.get('source') == entity_name]
        related_relationships.extend(source_rels)
        
        # 作为target的关系
        target_rels = [r for r in relationships if r.get('target') == entity_name]
        related_relationships.extend(target_rels)
        
        # 生成Episode内容
        episode_content = f"{entity_name}"
        
        if entity_type == "Person":
            episode_content += "是一位用户"
            if entity_id:
                episode_content += f"，微信ID是{entity_id}"
        elif entity_type == "Context":
            episode_content += "是一个重要的上下文环境"
            if entity_desc:
                episode_content += f"：{entity_desc}"
        
        episode_content += "。"
        
        # 添加关系信息
        if related_relationships:
            episode_content += f"{entity_name}具有以下关系："
            
            for rel in related_relationships:
                rel_type = rel.get('type', '')
                source = rel.get('source', '')
                target = rel.get('target', '')
                time_info = rel.get('time', '')
                relation_info = rel.get('relation', '')
                
                if rel_type == "MEMBER_OF" and source == entity_name:
                    episode_content += f"是{target}的成员；"
                elif rel_type == "INVOLVE" and source == entity_name:
                    episode_content += f"参与了{target}"
                    if time_info:
                        episode_content += f"（{time_info}）"
                    episode_content += "；"
                elif rel_type == "KNOWS":
                    other_person = target if source == entity_name else source
                    episode_content += f"与{other_person}是{relation_info}关系；"
                elif rel_type == "MEMBER_OF" and target == entity_name:
                    episode_content += f"{source}是其成员；"
                elif rel_type == "INVOLVE" and target == entity_name:
                    episode_content += f"{source}参与了此活动"
                    if time_info:
                        episode_content += f"（{time_info}）"
                    episode_content += "；"
        
        # 生成唯一ID
        episode_id = self._generate_episode_id(f"entity_{entity_name}")
        
        # 检查重复
        if self._is_duplicate_episode(episode_id):
            return None
        
        return {
            "name": f"{entity_type}: {entity_name}",
            "episode_body": episode_content,
            "source_description": f"{entity_type} information from {source_file}",
            "reference_time": datetime.now(timezone.utc)
        }
    
    
    async def process_specific_files(self, json_files: List[Path], file_processed_callback=None) -> tuple[List[Dict[str, Any]], List[str]]:
        """
        处理指定的JSON文件列表
        
        Args:
            json_files: JSON文件Path对象列表
            file_processed_callback: 每处理完一个文件后的回调函数，参数为文件名
            
        Returns:
            tuple[List[Dict[str, Any]], List[str]]: (生成的Graphiti Episode列表, 成功处理的文件名列表)
        """
        all_episodes = []
        successfully_processed_files = []
        
        logger.info(f"处理指定的 {len(json_files)} 个JSON文件")
        
        # 重置去重状态
        self.global_episode_ids.clear()
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                episodes = self._convert_json_to_episodes(data, json_file.name)
                all_episodes.extend(episodes)
                successfully_processed_files.append(json_file.name)  # 只有成功处理才加入
                logger.info(f"文件 {json_file.name} 生成 {len(episodes)} 个Episode")
                
                # 立即调用回调函数，记录已处理的文件
                if file_processed_callback:
                    file_processed_callback(json_file.name)
                
            except Exception as e:
                logger.error(f"处理文件 {json_file} 失败: {e}")
                # 失败的文件不加入 successfully_processed_files
        
        logger.info(f"总共生成 {len(all_episodes)} 个去重后的Episode")
        logger.info(f"去重统计: {len(self.global_episode_ids)} 个唯一Episode ID")
        logger.info(f"成功处理 {len(successfully_processed_files)} 个文件")
        
        return all_episodes, successfully_processed_files

    async def process_wechat_data(self, input_directory: str) -> tuple[List[Dict[str, Any]], List[str]]:
        """
        处理微信数据，生成Graphiti Episodes
        
        Args:
            input_directory: 输入目录路径
            
        Returns:
            tuple[List[Dict[str, Any]], List[str]]: (生成的Graphiti Episode列表, 成功处理的文件名列表)
        """
        input_path = Path(input_directory)
        all_episodes = []
        successfully_processed_files = []
        
        # 获取所有JSON文件
        json_files = list(input_path.glob("*.json"))
        logger.info(f"找到 {len(json_files)} 个JSON文件")
        
        # 重置去重状态
        self.global_episode_ids.clear()
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                episodes = self._convert_json_to_episodes(data, json_file.name)
                all_episodes.extend(episodes)
                successfully_processed_files.append(json_file.name)  # 只有成功处理才加入
                logger.info(f"文件 {json_file.name} 生成 {len(episodes)} 个Episode")
                
            except Exception as e:
                logger.error(f"处理文件 {json_file} 失败: {e}")
                # 失败的文件不加入 successfully_processed_files
        
        logger.info(f"总共生成 {len(all_episodes)} 个去重后的Episode")
        logger.info(f"去重统计: {len(self.global_episode_ids)} 个唯一Episode ID")
        logger.info(f"成功处理 {len(successfully_processed_files)} 个文件")
        
        return all_episodes, successfully_processed_files
    
    async def process_and_store_wechat_data(self, input_directory: str, specific_files: List[str] = None) -> EpisodeGenerationResult:
        """
        处理微信数据并存储到Neo4j数据库
        
        Args:
            input_directory: 输入目录路径
            
        Returns:
            EpisodeGenerationResult: 处理和存储结果
        """
        processed_files = []
        
        try:
            # 初始化Graphiti客户端
            await self.client.initialize()
            
            # 处理数据生成Episodes，获取成功处理的文件列表
            episodes, processed_files = await self.process_wechat_data(input_directory)
            
            if not episodes:
                logger.warning("没有Episode需要存储")
                return EpisodeGenerationResult(
                    success=True,
                    total_episodes=0,
                    episodes_by_type={},
                    processed_files=processed_files  # 记录成功处理的文件
                )
            
            # 批量存储到Neo4j
            logger.info(f"开始存储 {len(episodes)} 个Episode到Neo4j")
            result = await self.client.add_graphiti_episodes_bulk(episodes)
            
            if result.success:
                logger.info(f"成功存储 {result.total_episodes} 个Episode到Neo4j")
                # 存储成功后记录处理的文件
                result.processed_files = processed_files
            else:
                logger.error(f"存储Episode失败: {result.errors}")
                # 存储失败时不记录processed_files，让文件下次重新处理
                result.processed_files = []
            
            return result
            
        except Exception as e:
            logger.error(f"处理和存储微信数据失败: {e}")
            return EpisodeGenerationResult(
                success=False,
                total_episodes=0,
                errors=[str(e)],
                processed_files=[]  # 出错时不记录processed_files
            )
    
    async def close(self):
        """关闭处理器"""
        await self.client.close()
    
    def get_episode_statistics(self) -> Dict[str, int]:
        """获取Episode统计信息"""
        return {
            "total_episodes": len(self.global_episode_ids),
            "unique_episode_ids": len(self.global_episode_ids)
        }


# 便利函数
async def process_wechat_data(input_directory: str) -> tuple[List[Dict[str, Any]], List[str]]:
    """
    便利函数：处理微信数据
    
    Args:
        input_directory: 输入目录路径
        
    Returns:
        tuple[List[Dict[str, Any]], List[str]]: (生成的Graphiti Episode列表, 成功处理的文件名列表)
    """
    processor = WeChatDataProcessor()
    try:
        return await processor.process_wechat_data(input_directory)
    finally:
        await processor.close()