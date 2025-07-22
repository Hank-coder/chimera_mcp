#!/usr/bin/env python3
"""
Neo4j数据同步脚本
将本地Neo4j数据同步到云服务器
保证两边数据同步
运行
python scripts/neo4j_sync.py sync --clear-target --source-uri neo4j://127.0.0.1:7687 --target-uri neo4j://117.72.96.19:7687 --username neo4j --password 1qw23er4
"""

import asyncio
import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any
from loguru import logger
from neo4j import AsyncGraphDatabase
import json
from datetime import datetime

# 确保项目根目录在Python路径中
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings


class Neo4jSyncManager:
    """Neo4j数据同步管理器"""
    
    def __init__(self, source_config: Dict[str, str], target_config: Dict[str, str]):
        self.source_config = source_config
        self.target_config = target_config
        self.source_driver = None
        self.target_driver = None
    
    async def initialize(self):
        """初始化数据库连接"""
        logger.info("初始化数据库连接...")
        
        # 源数据库连接（本地）
        self.source_driver = AsyncGraphDatabase.driver(
            self.source_config['uri'],
            auth=(self.source_config['username'], self.source_config['password'])
        )
        
        # 目标数据库连接（云服务器）
        self.target_driver = AsyncGraphDatabase.driver(
            self.target_config['uri'],
            auth=(self.target_config['username'], self.target_config['password'])
        )
        
        # 测试连接
        await self._test_connections()
        logger.info("数据库连接初始化成功")
    
    async def _test_connections(self):
        """测试数据库连接"""
        try:
            # 测试源数据库
            async with self.source_driver.session() as session:
                result = await session.run("RETURN 1 as test")
                await result.consume()
            logger.info("✅ 源数据库连接成功")
            
            # 测试目标数据库
            async with self.target_driver.session() as session:
                result = await session.run("RETURN 1 as test")
                await result.consume()
            logger.info("✅ 目标数据库连接成功")
            
        except Exception as e:
            logger.error(f"数据库连接测试失败: {e}")
            raise
    
    async def export_data(self) -> Dict[str, List[Dict[str, Any]]]:
        """从源数据库导出数据"""
        logger.info("开始从源数据库导出数据...")
        
        exported_data = {
            'nodes': [],
            'relationships': []
        }
        
        async with self.source_driver.session() as session:
            # 导出所有节点
            logger.info("导出节点数据...")
            node_query = """
            MATCH (n)
            RETURN labels(n) as labels, properties(n) as properties, id(n) as internal_id
            """
            
            result = await session.run(node_query)
            async for record in result:
                node_data = {
                    'labels': record['labels'],
                    'properties': dict(record['properties']),
                    'internal_id': record['internal_id']
                }
                exported_data['nodes'].append(node_data)
            
            logger.info(f"导出了 {len(exported_data['nodes'])} 个节点")
            
            # 导出所有关系
            logger.info("导出关系数据...")
            rel_query = """
            MATCH (a)-[r]->(b)
            RETURN type(r) as type, properties(r) as properties, 
                   id(a) as start_id, id(b) as end_id,
                   labels(a) as start_labels, labels(b) as end_labels,
                   properties(a) as start_properties, properties(b) as end_properties
            """
            
            result = await session.run(rel_query)
            async for record in result:
                rel_data = {
                    'type': record['type'],
                    'properties': dict(record['properties']),
                    'start_node': {
                        'internal_id': record['start_id'],
                        'labels': record['start_labels'],
                        'properties': dict(record['start_properties'])
                    },
                    'end_node': {
                        'internal_id': record['end_id'],
                        'labels': record['end_labels'],
                        'properties': dict(record['end_properties'])
                    }
                }
                exported_data['relationships'].append(rel_data)
            
            logger.info(f"导出了 {len(exported_data['relationships'])} 个关系")
        
        return exported_data
    
    async def clear_target_database(self):
        """清空目标数据库"""
        logger.warning("⚠️  准备清空目标数据库...")
        
        async with self.target_driver.session() as session:
            # 删除所有关系
            await session.run("MATCH ()-[r]-() DELETE r")
            # 删除所有节点
            await session.run("MATCH (n) DELETE n")
            # 删除所有索引和约束（如果需要）
            
        logger.info("✅ 目标数据库已清空")
    
    async def import_data(self, data: Dict[str, List[Dict[str, Any]]]):
        """将数据导入目标数据库"""
        logger.info("开始向目标数据库导入数据...")
        
        # 创建节点ID映射
        node_id_mapping = {}
        
        async with self.target_driver.session() as session:
            # 导入节点
            logger.info("导入节点数据...")
            for i, node in enumerate(data['nodes']):
                labels_str = ':'.join(node['labels']) if node['labels'] else 'Node'
                
                # 构建CREATE语句
                create_query = f"CREATE (n:{labels_str}) SET n = $properties RETURN id(n) as new_id"
                
                result = await session.run(create_query, properties=node['properties'])
                record = await result.single()
                new_id = record['new_id']
                
                # 记录ID映射
                node_id_mapping[node['internal_id']] = new_id
                
                if (i + 1) % 100 == 0:
                    logger.info(f"已导入 {i + 1}/{len(data['nodes'])} 个节点")
            
            logger.info(f"✅ 成功导入 {len(data['nodes'])} 个节点")
            
            # 导入关系
            logger.info("导入关系数据...")
            for i, rel in enumerate(data['relationships']):
                start_old_id = rel['start_node']['internal_id']
                end_old_id = rel['end_node']['internal_id']
                
                # 获取新的节点ID
                start_new_id = node_id_mapping.get(start_old_id)
                end_new_id = node_id_mapping.get(end_old_id)
                
                if start_new_id is None or end_new_id is None:
                    logger.warning(f"跳过关系 {i}：找不到对应的节点ID")
                    continue
                
                # 创建关系
                rel_type = rel['type']
                create_rel_query = f"""
                MATCH (a), (b)
                WHERE id(a) = $start_id AND id(b) = $end_id
                CREATE (a)-[r:{rel_type}]->(b)
                SET r = $properties
                """
                
                await session.run(
                    create_rel_query,
                    start_id=start_new_id,
                    end_id=end_new_id,
                    properties=rel['properties']
                )
                
                if (i + 1) % 100 == 0:
                    logger.info(f"已导入 {i + 1}/{len(data['relationships'])} 个关系")
            
            logger.info(f"✅ 成功导入 {len(data['relationships'])} 个关系")
    
    async def sync_full(self, clear_target: bool = False):
        """执行完整同步"""
        logger.info("🚀 开始执行完整数据同步...")
        
        try:
            # 导出源数据
            data = await self.export_data()
            
            # 可选：清空目标数据库
            if clear_target:
                await self.clear_target_database()
            
            # 导入数据
            await self.import_data(data)
            
            logger.info("🎉 数据同步完成！")
            
            # 验证同步结果
            await self._verify_sync()
            
        except Exception as e:
            logger.error(f"数据同步失败: {e}")
            raise
    
    async def _verify_sync(self):
        """验证同步结果"""
        logger.info("验证同步结果...")
        
        async with self.source_driver.session() as source_session:
            # 统计源数据库
            source_nodes = await source_session.run("MATCH (n) RETURN count(n) as count")
            source_node_count = (await source_nodes.single())['count']
            
            source_rels = await source_session.run("MATCH ()-[r]-() RETURN count(r) as count")
            source_rel_count = (await source_rels.single())['count']
        
        async with self.target_driver.session() as target_session:
            # 统计目标数据库
            target_nodes = await target_session.run("MATCH (n) RETURN count(n) as count")
            target_node_count = (await target_nodes.single())['count']
            
            target_rels = await target_session.run("MATCH ()-[r]-() RETURN count(r) as count")
            target_rel_count = (await target_rels.single())['count']
        
        logger.info(f"同步验证结果：")
        logger.info(f"  节点: 源={source_node_count}, 目标={target_node_count}")
        logger.info(f"  关系: 源={source_rel_count}, 目标={target_rel_count}")
        
        if source_node_count == target_node_count and source_rel_count == target_rel_count:
            logger.info("✅ 同步验证通过！")
        else:
            logger.warning("⚠️  同步验证失败，数据量不匹配")
    
    async def close(self):
        """关闭数据库连接"""
        if self.source_driver:
            await self.source_driver.close()
        if self.target_driver:
            await self.target_driver.close()


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Neo4j数据同步脚本")
    parser.add_argument("command", choices=["sync", "export", "import", "verify"], 
                       help="执行的命令")
    parser.add_argument("--clear-target", action="store_true",
                       help="同步前清空目标数据库")
    parser.add_argument("--source-uri", default="neo4j://127.0.0.1:7687",
                       help="源数据库URI")
    parser.add_argument("--target-uri", default="neo4j://117.72.96.19:7687",
                       help="目标数据库URI")
    parser.add_argument("--username", default="neo4j",
                       help="数据库用户名")
    parser.add_argument("--password", default="1qw23er4",
                       help="数据库密码")
    parser.add_argument("--log-level", default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="日志级别")
    
    args = parser.parse_args()
    
    # 配置日志
    logger.remove()
    logger.add(sys.stderr, level=args.log_level)
    
    # 配置数据库连接
    source_config = {
        'uri': args.source_uri,
        'username': args.username,
        'password': args.password
    }
    
    target_config = {
        'uri': args.target_uri,
        'username': args.username,
        'password': args.password
    }
    
    sync_manager = Neo4jSyncManager(source_config, target_config)
    
    try:
        await sync_manager.initialize()
        
        if args.command == "sync":
            await sync_manager.sync_full(clear_target=args.clear_target)
        elif args.command == "export":
            data = await sync_manager.export_data()
            # 保存到文件
            export_file = f"neo4j_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"数据已导出到: {export_file}")
        elif args.command == "verify":
            await sync_manager._verify_sync()
        
    except KeyboardInterrupt:
        logger.info("⏹️  用户中断操作")
        sys.exit(1)
    except Exception as e:
        logger.error(f"脚本执行失败: {e}")
        sys.exit(1)
    finally:
        await sync_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

