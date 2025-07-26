"""
Deep Research Director - 总控智能体
负责整个深度研究流程的协调和管理
"""

import asyncio
import time
from typing import List, Dict, Any, Optional
from loguru import logger

from .base import BaseAgent, BatchProcessor, calculate_optimal_clusters, format_processing_metadata
from .worker import OptimizedWorker
from core.models import (
    DeepResearchRequest,
    ResearchContext,
    TopicCluster,
    PageAnalysis,
    ResearchFramework,
    RESEARCH_COMPLEXITY_CONFIGS,
    ClusteringResponse
)


class ContextEngineeringDirector(BaseAgent):
    """
    Context Engineering总控智能体
    
    职责：
    1. 验证页面结构
    2. 子图BFS遍历 
    3. 语义分簇
    4. 4-Worker工蜂 固定架构调度
    5. 结果合并和Context优化
    """
    
    def __init__(self):
        super().__init__(agent_id="context_director")
        self.worker_count = 4  # 固定4个Worker，降低并发压力
        self.batch_processor = BatchProcessor(max_concurrent=self.worker_count)
        
    async def orchestrate_research(self, request: DeepResearchRequest) -> ResearchContext:
        """
        协调整个深度研究流程
        """
        start_time = time.time()
        
        try:
            logger.info(f"开始深度研究：page_id={request.page_id}, complexity={request.research_complexity}")
            
            # 1. 验证页面结构
            validation = await self.notion_client.validate_page_structure(request.page_id)
            if not validation["valid"]:
                raise ValueError(validation["error"])
            
            # logger.info(f"页面验证通过：{validation['child_count']} 个子页面")
            
            # 2. 子图BFS遍历（应用max_pages限制）
            candidate_pages = await self.notion_client.get_child_pages_bfs(
                request.page_id, request.depth, request.max_pages
            )
            if not candidate_pages:
                raise ValueError("未找到可分析的子页面")
            
            logger.info(f"BFS遍历完成：找到 {len(candidate_pages)} 个候选页面")
            
            # 3. 语义分簇
            target_clusters = calculate_optimal_clusters(len(candidate_pages), self.worker_count)
            clusters = await self.semantic_clustering(candidate_pages, target_clusters, request.research_complexity)
            
            logger.info(f"语义分簇完成：生成 {len(clusters)} 个主题簇")
            
            # 4. 4个Worker并发处理
            cluster_summaries = await self.dispatch_workers(clusters, request)
            
            logger.info(f"Worker处理完成：{len(cluster_summaries)} 个簇摘要")
            
            # 5. 直接拼接摘要，跳过复杂的Reduce步骤
            research_context = await self.create_research_context_from_summaries(
                cluster_summaries, request
            )
            
            # 6. 最终验证和优化
            research_context = await self.finalize_research_context(
                research_context, request
            )
            
            elapsed = time.time() - start_time
            logger.info(f"深度研究完成，总耗时: {elapsed:.2f}s")
            
            return research_context
            
        except Exception as e:
            logger.error(f"深度研究流程失败: {e}")
            raise
    
    async def semantic_clustering(
        self, 
        pages: List[Dict[str, Any]], 
        target_clusters: int,
        complexity: str
    ) -> List[List[Dict[str, Any]]]:
        """
        语义分簇：根据页面内容进行主题聚类
        """
        try:
            # logger.info(f"开始语义分簇：{len(pages)} 个页面 -> {target_clusters} 个簇")
            
            # 创建分簇prompt
            clustering_prompt = self.prompts.create_clustering_prompt(
                complexity=complexity,
                page_metadata=pages,
                target_clusters=target_clusters
            )
            
            # 调用Gemini进行分簇
            clustering_result = await self.call_gemini_structured(clustering_prompt)
            
            # 尝试从结构化结果或文本响应中提取信息
            clusters_data = []
            if "clustering_result" in clustering_result:
                clusters_data = clustering_result["clustering_result"].get("clusters", [])
            elif "text_response" in clustering_result:
                # 如果是文本响应，使用简单解析
                clusters_data = self._parse_text_clustering(clustering_result["text_response"], pages)
            else:
                # 尝试直接从结果中获取
                clusters_data = clustering_result.get("clusters", [])
            
            if not clusters_data:
                # 降级策略：使用智能标签分簇
                logger.warning("语义分簇失败，使用智能标签分簇")
                return self._tag_based_clustering(pages, target_clusters)
            
            # 构建页面ID到页面数据的映射
            page_map = {page["notion_id"]: page for page in pages}
            
            # 根据分簇结果组织页面
            clusters = []
            for cluster_info in clusters_data:
                cluster_pages = []
                for page_id in cluster_info.get("page_ids", []):
                    if page_id in page_map:
                        cluster_pages.append(page_map[page_id])
                
                if cluster_pages:
                    clusters.append(cluster_pages)
            
            # 确保所有页面都被分配
            assigned_page_ids = set()
            for cluster in clusters:
                for page in cluster:
                    assigned_page_ids.add(page["notion_id"])
            
            # 处理未分配的页面
            unassigned_pages = [p for p in pages if p["notion_id"] not in assigned_page_ids]
            if unassigned_pages:
                # logger.warning(f"有 {len(unassigned_pages)} 个页面未被分配，补充到最小簇")
                if clusters:
                    # 找到最小的簇并添加未分配页面
                    smallest_cluster = min(clusters, key=len)
                    smallest_cluster.extend(unassigned_pages)
                else:
                    # 如果没有有效簇，创建一个新簇
                    clusters.append(unassigned_pages)
            
            # logger.info(f"语义分簇完成：{[len(cluster) for cluster in clusters]}")
            return clusters
            
        except Exception as e:
            logger.error(f"语义分簇失败: {e}")
            # 降级策略：使用智能标签分簇
            return self._tag_based_clustering(pages, target_clusters)
    
    def _tag_based_clustering(self, pages: List[Dict], target_clusters: int) -> List[List[Dict]]:
        """基于标签和层级的智能分簇"""
        if not pages:
            return []
        
        # 1. 按标签进行初步分组
        tag_groups = {}
        no_tag_pages = []
        
        for page in pages:
            page_tags = page.get('tags', [])
            if page_tags:
                # 使用第一个标签作为主分组
                main_tag = page_tags[0]
                if main_tag not in tag_groups:
                    tag_groups[main_tag] = []
                tag_groups[main_tag].append(page)
            else:
                no_tag_pages.append(page)
        
        # 2. 按层级进一步分组
        level_groups = {}
        for page in no_tag_pages:
            level = page.get('level', 0)
            if level not in level_groups:
                level_groups[level] = []
            level_groups[level].append(page)
        
        # 3. 合并所有分组
        all_groups = list(tag_groups.values()) + list(level_groups.values())
        
        # 4. 调整到目标簇数
        if len(all_groups) > target_clusters:
            # 合并小组
            all_groups.sort(key=len)  # 按大小排序
            while len(all_groups) > target_clusters:
                smallest = all_groups.pop(0)
                all_groups[0].extend(smallest)  # 合并到下一个最小组
        elif len(all_groups) < target_clusters:
            # 拆分大组
            while len(all_groups) < target_clusters and any(len(group) > 1 for group in all_groups):
                # 找到最大的组进行拆分
                largest_idx = max(range(len(all_groups)), key=lambda i: len(all_groups[i]))
                largest_group = all_groups[largest_idx]
                if len(largest_group) > 1:
                    # 拆分成两部分
                    mid = len(largest_group) // 2
                    group1 = largest_group[:mid]
                    group2 = largest_group[mid:]
                    all_groups[largest_idx] = group1
                    all_groups.append(group2)
                else:
                    break
        
        # 5. 如果还是没有足够的组，使用简单均分
        if not all_groups:
            return self._simple_balanced_clustering(pages, target_clusters)
        
        return all_groups
    
    def _simple_balanced_clustering(self, pages: List[Dict], target_clusters: int) -> List[List[Dict]]:
        """简单的负载均衡分簇（降级策略）"""
        return self.create_balanced_batches(pages, target_clusters)
    
    async def dispatch_workers(
        self, 
        clusters: List[List[Dict]], 
        request: DeepResearchRequest
    ) -> List[str]:
        """
        调度4个Worker 工蜂并发处理各个簇，返回文本摘要列表
        """
        try:
            # logger.info(f"调度 {len(clusters)} 个Worker处理簇")
            
            # 确保不超过最大Worker数量
            if len(clusters) > self.worker_count:
                # logger.warning(f"簇数量 {len(clusters)} 超过Worker数量 {self.worker_count}，进行合并")
                clusters = self._merge_excess_clusters(clusters, self.worker_count)
            
            # 创建Worker任务
            worker_tasks = []
            for i, cluster_pages in enumerate(clusters):
                worker = OptimizedWorker(
                    worker_id=f"worker_{i}",
                    complexity_config=RESEARCH_COMPLEXITY_CONFIGS[request.research_complexity],
                    research_purpose=request.purpose
                )
                
                task = worker.process_cluster(
                    cluster_pages=cluster_pages,
                    cluster_theme=f"主题簇_{i+1}",
                    max_pages=request.max_pages
                )
                worker_tasks.append(task)
            
            # 并发执行所有Worker
            results = await asyncio.gather(*worker_tasks, return_exceptions=True)
            
            # 处理结果和异常
            cluster_summaries = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Worker {i} 处理失败: {result}")
                    # 创建降级结果
                    fallback_summary = f"主题簇_{i+1}\n\nWorker {i} 处理失败：{str(result)}\n请手动查看相关页面获取详细信息。"
                    cluster_summaries.append(fallback_summary)
                else:
                    cluster_summaries.append(result)
            
            logger.info(f"Worker调度完成：{len(cluster_summaries)} 个簇摘要")
            return cluster_summaries
            
        except Exception as e:
            logger.error(f"Worker调度失败: {e}")
            raise
    
    def _merge_excess_clusters(self, clusters: List[List[Dict]], max_clusters: int) -> List[List[Dict]]:
        """合并多余的簇"""
        if len(clusters) <= max_clusters:
            return clusters
        
        # 按簇大小排序，小簇优先合并
        sorted_clusters = sorted(clusters, key=len)
        
        # 保留最大的max_clusters个簇
        merged_clusters = sorted_clusters[-max_clusters:]
        
        # 将小簇合并到最后一个簇中
        excess_clusters = sorted_clusters[:-max_clusters]
        for excess_cluster in excess_clusters:
            merged_clusters[-1].extend(excess_cluster)
        
        return merged_clusters
    
    async def _create_fallback_cluster(
        self, 
        cluster_pages: List[Dict], 
        cluster_id: str,
        complexity: str
    ) -> TopicCluster:
        """创建降级簇结果"""
        
        # 生成基础页面分析
        fallback_pages = []
        for page in cluster_pages[:3]:  # 只处理前3个页面
            page_analysis = PageAnalysis(
                notion_id=page["notion_id"],
                title=page["title"],
                content="内容获取失败",
                summary=f"页面 {page['title']} 的基础摘要（降级模式）",
                key_points=[
                    f"页面标题：{page['title']}",
                    f"页面标签：{', '.join(page.get('tags', []))}",
                    "详细内容需要手动查看"
                ],
                importance_score=0.5,
                relevance_score=0.3,
                word_count=0,
                supporting_quotes=[],
                research_value={
                    "theoretical_contribution": "未评估",
                    "practical_application": "未评估",
                    "citation_worthiness": "未评估"
                }
            )
            fallback_pages.append(page_analysis)
        
        return TopicCluster(
            cluster_id=cluster_id,
            theme="降级处理簇",
            pages=fallback_pages,
            cluster_synthesis="由于处理失败，此簇使用降级策略生成基础结果。建议手动查看相关页面获取详细信息。",
            representative_quotes=[],
            cross_references=[]
        )
    
    async def create_research_context_from_summaries(
        self,
        cluster_summaries: List[str],
        request: DeepResearchRequest
    ) -> ResearchContext:
        """
        基于工蜂返回的摘要直接创建研究上下文，跳过复杂的Reduce步骤
        """
        try:
            # logger.info(f"开始创建研究上下文：{len(cluster_summaries)} 个簇摘要")
            
            # 直接拼接所有簇摘要
            combined_summary = f"基于 {request.research_complexity} 级别的深度研究分析\n"
            combined_summary += f"研究目的：{request.purpose}\n\n"
            combined_summary += "=" * 50 + "\n\n"
            combined_summary += "\n\n".join(cluster_summaries)
            
            # 创建简化的研究框架
            research_framework = ResearchFramework(
                problem_definition=f"针对 '{request.purpose}' 的研究分析",
                theoretical_foundation=f"基于 {len(cluster_summaries)} 个主题域的综合分析",
                methodology_insights="采用多智能体协作的知识图谱遍历与内容聚类方法",
                expected_contributions=f"提供结构化的研究参考和洞察"
            )
            
            # 提取关键洞察（从摘要中）
            key_insights = []
            for i, summary in enumerate(cluster_summaries):
                # 简单提取：取每个摘要的前100字符作为洞察
                insight = summary.split('\n\n')[0] if '\n\n' in summary else summary[:100]
                key_insights.append(f"洞察{i+1}: {insight}...")
            
            # 构建最终研究上下文
            research_context = ResearchContext(
                executive_summary=combined_summary,
                topic_clusters=[],  # 简化版本不需要复杂的TopicCluster对象
                top_pages=[],       # 简化版本不需要PageAnalysis对象
                key_insights=key_insights,
                supporting_evidence=[],
                research_framework=research_framework,
                future_directions=[
                    "基于当前分析结果，可进一步深入特定主题领域",
                    "建议结合实际应用场景进行验证和优化",
                    "可扩展分析范围以获得更全面的洞察"
                ],
                research_scope={
                    "total_clusters_analyzed": len(cluster_summaries),
                    "complexity_level": request.research_complexity,
                    "processing_mode": "simplified_aggregation",
                    "data_integration_mode": "direct_summary_concatenation"
                }
            )
            
            # logger.info("研究上下文创建完成（简化模式）")
            return research_context
            
        except Exception as e:
            logger.error(f"研究上下文创建失败: {e}")
            # 返回基础的研究上下文
            return self._create_basic_research_context_from_summaries(cluster_summaries, request)
    
    def _create_basic_research_context_from_summaries(
        self, 
        cluster_summaries: List[str], 
        request: DeepResearchRequest
    ) -> ResearchContext:
        """创建基础的研究上下文（降级策略）"""
        
        basic_summary = f"研究分析（降级模式）\n研究目的：{request.purpose}\n\n"
        basic_summary += "由于处理过程中出现问题，以下是基础的分析结果：\n\n"
        
        for i, summary in enumerate(cluster_summaries):
            basic_summary += f"簇 {i+1}：{summary[:200]}...\n\n"
        
        return ResearchContext(
            executive_summary=basic_summary,
            topic_clusters=[],
            top_pages=[],
            key_insights=[
                f"共处理了 {len(cluster_summaries)} 个主题簇",
                f"研究复杂度：{request.research_complexity}",
                "建议手动查看详细内容以获得更深入的理解"
            ],
            supporting_evidence=[],
            research_framework=ResearchFramework(
                problem_definition="基础分析模式",
                theoretical_foundation="基于简化的内容聚类",
                methodology_insights="多智能体协作处理（降级模式）",
                expected_contributions="提供基础的结构化参考"
            ),
            future_directions=[
                "重新运行分析以获得更详细的结果",
                "手动查看相关页面以获得完整信息"
            ],
            research_scope={
                "total_clusters_analyzed": len(cluster_summaries),
                "complexity_level": request.research_complexity,
                "status": "fallback_mode"
            }
        )
    
    async def synthesize_research_context(
        self, 
        cluster_results: List[TopicCluster], 
        request: DeepResearchRequest
    ) -> ResearchContext:
        """
        基于Worker结果进行数据整合（不调用LLM）
        """
        try:
            # logger.info(f"开始整合研究上下文：{len(cluster_results)} 个簇")
            
            # 收集所有页面并排序
            all_pages = []
            for cluster in cluster_results:
                all_pages.extend(cluster.pages)
            
            # 选择Top-N页面（基于重要性和关联度排序）
            top_pages = self._select_top_pages(all_pages, request.max_pages)
            
            # 提取关键洞察（从各簇的综合分析中）
            key_insights = []
            for cluster in cluster_results:
                if cluster.cluster_synthesis and len(cluster.cluster_synthesis) > 50:
                    # 提取前100字符作为核心洞察
                    insight = cluster.cluster_synthesis[:100] + "..."
                    key_insights.append(f"[{cluster.theme}] {insight}")
            
            # 收集支撑证据
            supporting_evidence = []
            for cluster in cluster_results:
                for quote in cluster.representative_quotes[:2]:
                    supporting_evidence.append({
                        "source_cluster": cluster.theme,
                        "evidence_type": "代表性引用",
                        "content": quote,
                        "relevance": "high"
                    })
            
            # 生成执行摘要（基于数据统计）
            avg_relevance = sum(p.relevance_score for p in all_pages) / len(all_pages) if all_pages else 0
            avg_importance = sum(p.importance_score for p in all_pages) / len(all_pages) if all_pages else 0
            
            executive_summary = f"""基于 {request.research_complexity} 级别的深度研究分析，共处理 {len(all_pages)} 个页面，形成 {len(cluster_results)} 个主题簇。

研究范围：{request.purpose}

关键统计：
- 平均关联度：{avg_relevance:.2f}
- 平均重要性：{avg_importance:.2f}  
- 顶级页面：{len(top_pages)} 个
- 主要主题：{', '.join([c.theme for c in cluster_results[:3]])}

本研究通过多智能体协作分析，系统梳理了相关领域的核心内容，为后续深入研究提供了结构化的知识基础。"""

            # 构建研究框架（基于复杂度配置）
            complexity_config = RESEARCH_COMPLEXITY_CONFIGS.get(request.research_complexity)
            research_framework = ResearchFramework(
                problem_definition=f"针对 '{request.purpose}' 的 {request.research_complexity} 级研究",
                theoretical_foundation=f"基于 {len(cluster_results)} 个主题域的多维度分析框架",
                methodology_insights="采用多智能体协作的知识图谱遍历与内容聚类方法",
                expected_contributions=f"提供{complexity_config.detail_level if complexity_config else '标准'}级别的结构化研究上下文"
            )
            
            # 未来方向建议
            future_directions = [
                f"深入分析各主题簇之间的关联性",
                f"扩展相关领域的研究深度",
                f"建立更完整的知识体系框架"
            ]
            
            # 构建最终研究上下文
            research_context = ResearchContext(
                executive_summary=executive_summary,
                topic_clusters=cluster_results,
                top_pages=top_pages,
                key_insights=key_insights,
                supporting_evidence=supporting_evidence,
                research_framework=research_framework,
                future_directions=future_directions,
                research_scope={
                    "total_pages_analyzed": len(all_pages),
                    "clusters_formed": len(cluster_results),
                    "complexity_level": request.research_complexity,
                    "processing_metadata": format_processing_metadata(
                        self, len(all_pages), request.research_complexity
                    ),
                    "data_integration_mode": "worker_based"  # 标记为基于Worker的整合
                }
            )
            
            # logger.info("研究上下文整合完成")
            return research_context
            
        except Exception as e:
            logger.error(f"研究上下文整合失败: {e}")
            # 返回基础的研究上下文
            return self._create_basic_research_context(cluster_results, request)
    
    def _select_top_pages(self, all_pages: List[PageAnalysis], max_pages: int) -> List[PageAnalysis]:
        """基于综合评分选择Top-N页面"""
        
        if not all_pages:
            return []
        
        # 按综合评分排序：关联度60% + 重要性40%
        def combined_score(page: PageAnalysis) -> float:
            return page.relevance_score * 0.6 + page.importance_score * 0.4
        
        sorted_pages = sorted(all_pages, key=combined_score, reverse=True)
        
        # 选择前max_pages个
        top_pages = sorted_pages[:max_pages]
        
        # 计算统计信息
        if top_pages:
            avg_relevance = sum(p.relevance_score for p in top_pages) / len(top_pages)
            avg_importance = sum(p.importance_score for p in top_pages) / len(top_pages)
            # logger.info(f"选择了 {len(top_pages)} 个顶级页面，平均关联度: {avg_relevance:.2f}, 平均重要性: {avg_importance:.2f}")
        
        return top_pages
    
    def _create_basic_research_context(
        self, 
        cluster_results: List[TopicCluster], 
        request: DeepResearchRequest
    ) -> ResearchContext:
        """创建基础的研究上下文（降级策略）"""
        
        all_pages = []
        for cluster in cluster_results:
            all_pages.extend(cluster.pages)
        
        top_pages = self._select_top_pages(all_pages, request.max_pages)
        
        return ResearchContext(
            executive_summary=f"基于 {len(cluster_results)} 个主题簇的 {request.research_complexity} 级分析。由于合成过程出现问题，这是降级生成的基础摘要。",
            topic_clusters=cluster_results,
            top_pages=top_pages,
            key_insights=[
                f"共分析了 {len(all_pages)} 个页面",
                f"形成了 {len(cluster_results)} 个主题簇",
                f"选出了 {len(top_pages)} 个重点页面"
            ],
            supporting_evidence=[],
            research_framework=ResearchFramework(
                problem_definition="基础分析模式",
                theoretical_foundation="基于页面内容的聚类分析",
                methodology_insights="多智能体协作处理",
                expected_contributions="提供结构化的研究参考"
            ),
            future_directions=[
                "深入分析各主题簇的内在联系",
                "扩展相关领域的研究范围",
                "建立更完整的知识体系"
            ],
            research_scope={
                "total_pages_analyzed": len(all_pages),
                "clusters_formed": len(cluster_results),
                "complexity_level": request.research_complexity,
                "status": "fallback_mode"
            }
        )
    
    async def finalize_research_context(
        self, 
        research_context: ResearchContext, 
        request: DeepResearchRequest
    ) -> ResearchContext:
        """最终验证和优化研究上下文"""
        
        try:
            # 验证内容完整性
            if not research_context.executive_summary:
                research_context.executive_summary = "研究摘要生成失败，请查看详细的主题簇分析。"
            
            # 确保有足够的关键洞察
            if len(research_context.key_insights) < 3:
                research_context.key_insights.extend([
                    f"研究复杂度：{request.research_complexity}",
                    f"分析页面数量：{len(research_context.top_pages)}",
                    f"主题簇数量：{len(research_context.topic_clusters)}"
                ])
            
            # 更新处理元数据
            research_context.research_scope.update({
                "final_processing_time": self.processing_time,
                "total_api_calls": self.api_call_count,
                "worker_count_used": min(self.worker_count, len(research_context.topic_clusters))
            })
            
            logger.info("研究上下文最终验证完成")
            return research_context
            
        except Exception as e:
            logger.error(f"最终验证失败: {e}")
            return research_context
    
    async def process(self, request: DeepResearchRequest) -> ResearchContext:
        """BaseAgent要求实现的抽象方法"""
        return await self.orchestrate_research(request)