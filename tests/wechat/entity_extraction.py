#!/usr/bin/env python3
"""
测试Entity提取和Episode生成逻辑
以Entity为中心，每个Entity生成一个Episode
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any

# 确保项目根目录在Python路径中
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger

def extract_entity_episodes(json_file: str) -> List[Dict[str, Any]]:
    """
    从JSON文件提取Entity-centered Episodes
    
    Args:
        json_file: JSON文件路径
        
    Returns:
        List[Dict[str, Any]]: Episode列表
    """
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    entities = data.get('entities', [])
    relationships = data.get('relationships', [])
    
    logger.info(f"文件: {Path(json_file).name}")
    logger.info(f"  实体数量: {len(entities)}")
    logger.info(f"  关系数量: {len(relationships)}")
    
    episodes = []
    
    # 为每个Entity创建一个Episode
    for entity in entities:
        entity_name = entity.get('name', '')
        entity_type = entity.get('type', '')
        entity_id = entity.get('id', '')
        entity_desc = entity.get('description', '')
        
        if not entity_name:
            continue
        
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
            episode_content += f"{entity_name} 具有以下关系："
            
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
        
        # 创建Episode
        episode = {
            "name": f"{entity_type}: {entity_name}",
            "episode_body": episode_content,
            "source_description": f"{entity_type} information from {Path(json_file).name}",
            "entity_name": entity_name,
            "entity_type": entity_type,
            "relationship_count": len(related_relationships)
        }
        
        episodes.append(episode)
        
        # 打印详细信息
        logger.info(f"\n--- {entity_type}: {entity_name} ---")
        logger.info(f"关系数量: {len(related_relationships)}")
        logger.info(f"Episode长度: {len(episode_content)}字符")
        logger.info(f"内容预览: {episode_content[:100]}...")
    
    return episodes

def all_json_files():
    """测试所有JSON文件"""
    json_dir = Path("local_data/wechat/group")
    json_files = list(json_dir.glob("*.json"))
    
    logger.info(f"找到 {len(json_files)} 个JSON文件")
    
    all_episodes = []
    
    for json_file in json_files:
        logger.info(f"\n{'='*50}")
        logger.info(f"处理文件: {json_file.name}")
        
        episodes = extract_entity_episodes(json_file)
        all_episodes.extend(episodes)
        
        # 统计信息
        person_count = sum(1 for e in episodes if e['entity_type'] == 'Person')
        context_count = sum(1 for e in episodes if e['entity_type'] == 'Context')
        
        logger.info(f"生成Episode: {len(episodes)}个 (Person: {person_count}, Context: {context_count})")
    
    # 总体统计
    logger.info(f"\n{'='*50}")
    logger.info(f"总体统计:")
    logger.info(f"  总Episode数: {len(all_episodes)}")
    
    person_episodes = [e for e in all_episodes if e['entity_type'] == 'Person']
    context_episodes = [e for e in all_episodes if e['entity_type'] == 'Context']
    
    logger.info(f"  Person Episodes: {len(person_episodes)}")
    logger.info(f"  Context Episodes: {len(context_episodes)}")
    
    # 显示一些示例
    logger.info(f"\n示例Episode:")
    for i, episode in enumerate(all_episodes[:3]):
        logger.info(f"{i+1}. {episode['name']}")
        logger.info(f"   内容: {episode['episode_body'][:150]}...")
        logger.info(f"   关系数: {episode['relationship_count']}")
    
    return all_episodes

if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    
    logger.info("🧪 测试Entity提取和Episode生成")
    logger.info("="*50)
    
    all_episodes = all_json_files()
    
    logger.info(f"\n✅ 提取完成，总共生成 {len(all_episodes)} 个Episode")