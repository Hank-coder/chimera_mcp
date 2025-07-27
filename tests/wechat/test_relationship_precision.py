#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信关系搜索精确度测试
测试不同查询的precision和recall
"""

import asyncio
import sys
from pathlib import Path
from loguru import logger
from typing import List, Dict, Any
import json

# 确保项目根目录在Python路径中
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.wechat_search import search_wechat_relationships, close_searcher
from config.settings import get_settings
from neo4j import AsyncGraphDatabase


async def get_sample_entities() -> List[Dict[str, Any]]:
    """从数据库中获取10个样本实体"""
    settings = get_settings()
    
    logger.info("=== 获取数据库中的样本实体 ===")
    
    try:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password)
        )
        
        async with driver.session() as session:
            # 获取不同类型的实体样本
            query = """
            MATCH (e:Entity)
            RETURN e.uuid as uuid, 
                   e.name as name, 
                   e.summary as summary
            ORDER BY e.name
            LIMIT 15
            """
            
            result = await session.run(query)
            entities = []
            
            async for record in result:
                entity = {
                    'uuid': record['uuid'],
                    'name': record['name'],
                    'summary': record['summary'][:100] + '...' if len(record['summary']) > 100 else record['summary']
                }
                entities.append(entity)
            
            logger.info(f"找到 {len(entities)} 个实体样本:")
            for i, entity in enumerate(entities, 1):
                logger.info(f"{i:2d}. {entity['name']} - {entity['summary']}")
            
        await driver.close()
        return entities
        
    except Exception as e:
        logger.error(f"获取实体失败: {e}")
        return []


def design_test_cases(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """设计测试用例"""
    
    test_cases = []
    
    # 选择有代表性的实体进行测试
    selected_entities = entities[:10]  # 取前10个
    
    for entity in selected_entities:
        name = entity['name']
        
        # 设计不同类型的查询
        queries = []
        
        # 1. 完全匹配查询
        queries.append({
            'query': name,
            'type': 'exact_match',
            'expected_entity': name,
            'description': f'完全匹配查询: {name}'
        })
        
        # 2. 部分匹配查询（如果名字较长）
        if len(name) > 2:
            partial_name = name[:2] if len(name) > 3 else name[0]
            queries.append({
                'query': partial_name,
                'type': 'partial_match',
                'expected_entity': name,
                'description': f'部分匹配查询: {partial_name} (期望找到 {name})'
            })
        
        # 3. 模糊匹配查询（去掉特殊字符）
        clean_name = ''.join(c for c in name if c.isalnum() or c in '中文字符范围')
        if clean_name != name and len(clean_name) > 1:
            queries.append({
                'query': clean_name,
                'type': 'fuzzy_match',
                'expected_entity': name,
                'description': f'模糊匹配查询: {clean_name} (期望找到 {name})'
            })
        
        # 添加到测试用例
        for query_info in queries:
            test_case = {
                'entity': entity,
                'query_info': query_info
            }
            test_cases.append(test_case)
    
    return test_cases[:20]  # 限制为20个测试用例


async def run_precision_test(test_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """运行精确度测试"""
    
    logger.info(f"=== 开始精确度测试 ({len(test_cases)} 个测试用例) ===")
    
    results = {
        'total_tests': len(test_cases),
        'successful_matches': 0,
        'partial_matches': 0,
        'failed_matches': 0,
        'test_details': [],
        'precision_by_type': {}
    }
    
    type_stats = {}
    
    for i, test_case in enumerate(test_cases, 1):
        entity = test_case['entity']
        query_info = test_case['query_info']
        
        logger.info(f"\n--- 测试 {i}/{len(test_cases)}: {query_info['description']} ---")
        
        try:
            # 执行搜索
            search_result = await search_wechat_relationships(
                query=query_info['query'],
                max_results=5
            )
            
            if search_result.success:
                # Entity-first实现返回的是实体节点，直接提取实体名称
                found_entities = []
                expected_entity = query_info['expected_entity']
                
                for entity_result in search_result.results:
                    # 从实体结果中提取实体名称
                    entity_name = entity_result.get('name', '')
                    if entity_name:
                        found_entities.append(entity_name)
                    else:
                        found_entities.append('UNKNOWN')
                
                # 评估结果
                match_result = 'failed'
                if expected_entity in found_entities:
                    # 检查排名
                    rank = found_entities.index(expected_entity) + 1
                    if rank == 1:
                        match_result = 'perfect'  # 第一位
                        results['successful_matches'] += 1
                    else:
                        match_result = 'partial'  # 找到但不是第一位
                        results['partial_matches'] += 1
                else:
                    match_result = 'failed'
                    results['failed_matches'] += 1
                
                # 记录详细结果
                test_detail = {
                    'test_id': i,
                    'query': query_info['query'],
                    'query_type': query_info['type'],
                    'expected': expected_entity,
                    'found_entities': found_entities,
                    'match_result': match_result,
                    'rank': found_entities.index(expected_entity) + 1 if expected_entity in found_entities else -1,
                    'processing_time_ms': search_result.processing_time_ms
                }
                
                logger.info(f"查询: '{query_info['query']}'")
                logger.info(f"期望: {expected_entity}")
                logger.info(f"结果: {found_entities}")
                logger.info(f"匹配: {match_result} (排名: {test_detail['rank'] if test_detail['rank'] > 0 else 'N/A'})")
                
            else:
                match_result = 'error'
                results['failed_matches'] += 1
                test_detail = {
                    'test_id': i,
                    'query': query_info['query'],
                    'query_type': query_info['type'],
                    'expected': expected_entity,
                    'error': search_result.error,
                    'match_result': match_result
                }
                logger.error(f"搜索失败: {search_result.error}")
            
            results['test_details'].append(test_detail)
            
            # 按类型统计
            query_type = query_info['type']
            if query_type not in type_stats:
                type_stats[query_type] = {'total': 0, 'perfect': 0, 'partial': 0, 'failed': 0}
            
            type_stats[query_type]['total'] += 1
            if match_result == 'perfect':
                type_stats[query_type]['perfect'] += 1
            elif match_result == 'partial':
                type_stats[query_type]['partial'] += 1
            else:
                type_stats[query_type]['failed'] += 1
                
        except Exception as e:
            logger.error(f"测试 {i} 执行失败: {e}")
            results['failed_matches'] += 1
            results['test_details'].append({
                'test_id': i,
                'query': query_info['query'],
                'query_type': query_info['type'],
                'expected': entity['name'],
                'error': str(e),
                'match_result': 'error'
            })
    
    # 计算各类型精确度
    for query_type, stats in type_stats.items():
        if stats['total'] > 0:
            perfect_rate = stats['perfect'] / stats['total']
            partial_rate = stats['partial'] / stats['total']
            success_rate = (stats['perfect'] + stats['partial']) / stats['total']
            
            results['precision_by_type'][query_type] = {
                'perfect_precision': perfect_rate,
                'partial_precision': partial_rate,
                'total_success_rate': success_rate,
                'stats': stats
            }
    
    return results


def generate_test_report(results: Dict[str, Any]) -> str:
    """生成测试报告"""
    
    total = results['total_tests']
    perfect = results['successful_matches']
    partial = results['partial_matches']
    failed = results['failed_matches']
    
    # 总体精确度
    perfect_precision = perfect / total if total > 0 else 0
    partial_precision = partial / total if total > 0 else 0
    total_success_rate = (perfect + partial) / total if total > 0 else 0
    
    report = f"""
=== 微信关系搜索精确度测试报告 ===

📊 总体统计:
- 总测试数: {total}
- 完美匹配 (第1位): {perfect} ({perfect_precision:.1%})
- 部分匹配 (前5位): {partial} ({partial_precision:.1%})
- 匹配失败: {failed} ({failed/total:.1%})
- 总成功率: {perfect + partial} ({total_success_rate:.1%})

📈 按查询类型分析:
"""
    
    for query_type, metrics in results['precision_by_type'].items():
        stats = metrics['stats']
        report += f"""
🔍 {query_type}:
  - 完美匹配率: {metrics['perfect_precision']:.1%} ({stats['perfect']}/{stats['total']})
  - 部分匹配率: {metrics['partial_precision']:.1%} ({stats['partial']}/{stats['total']})
  - 总成功率: {metrics['total_success_rate']:.1%} ({stats['perfect'] + stats['partial']}/{stats['total']})
"""
    
    report += "\n📋 详细测试结果:\n"
    
    for detail in results['test_details']:
        status_emoji = {
            'perfect': '✅',
            'partial': '⚠️',
            'failed': '❌',
            'error': '💥'
        }.get(detail['match_result'], '❓')
        
        rank_info = f" (排名: {detail['rank']})" if detail.get('rank', -1) > 0 else ""
        
        report += f"{status_emoji} 测试{detail['test_id']}: '{detail['query']}' -> 期望: {detail['expected']}{rank_info}\n"
    
    return report


async def main():
    """主测试函数"""
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    
    logger.info("开始微信关系搜索精确度测试...")
    
    try:
        # 1. 获取样本实体
        entities = await get_sample_entities()
        if not entities:
            logger.error("无法获取实体样本，退出测试")
            return
        
        # 2. 设计测试用例
        test_cases = design_test_cases(entities)
        logger.info(f"设计了 {len(test_cases)} 个测试用例")
        
        # 3. 执行精确度测试
        results = await run_precision_test(test_cases)
        
        # 4. 生成并显示报告
        report = generate_test_report(results)
        print(report)
        
        # 5. 保存详细结果到文件
        with open('precision_test_results.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        logger.info("测试完成！详细结果已保存到 precision_test_results.json")
        
    finally:
        await close_searcher()


if __name__ == "__main__":
    asyncio.run(main())