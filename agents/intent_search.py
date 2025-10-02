"""
意图识别与路径搜索系统
用户输入一段话 → 意图识别 → 枚举Neo4j路径 → Gemini选择最合适路径 → 提取页面ID → 返回内容
"""

import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import json

from core.models import (
    IntentSearchRequest,
    IntentSearchResponse,
    IntentSearchMetadata,
    ConfidencePath,
    CorePageResult,
    RelatedPageResult,
    ConfidencePathMetadata,
    ConfidenceEvaluationResponse,
    GeminiAPIRequest,
    GeminiAPIResponse
)
from core.graphiti_client import GraphitiClient
from core.notion_client import NotionClient
from core.embedding_service import GoogleEmbeddingService
from core.embedding_search import EmbeddingSearchService
from prompts.intent_evaluation import IntentEvaluationPrompt
from utils.page_content_fetcher import get_page_content_for_intent_search
import google.generativeai as genai
from config.settings import settings


class IntentSearchEngine:
    """意图搜索引擎核心类"""
    
    def __init__(self):
        self.graphiti_client = GraphitiClient()
        self.notion_client = NotionClient()
        self.intent_prompt = IntentEvaluationPrompt()

        # 🆕 初始化embedding服务
        self.embedding_service = GoogleEmbeddingService()
        self.embedding_search_service = EmbeddingSearchService()

        # 配置Gemini
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.gemini_model = genai.GenerativeModel('gemini-2.0-flash')
    
    async def search_by_intent(self, user_input: str, **kwargs) -> IntentSearchResponse:
        """
        根据用户意图进行搜索的主函数

        Args:
            user_input: 用户输入的查询文本
            **kwargs: 可选参数，用于覆盖默认设置

        Returns:
            IntentSearchResponse: 完整的搜索结果
        """
        start_time = time.time()

        try:
            # 1. 意图关键词提取
            intent_keywords = await self._extract_intent_keywords(user_input)

            # 2. 构建搜索请求
            search_request = IntentSearchRequest(
                intent_keywords=intent_keywords,
                max_results=kwargs.get('max_results', 5),
                speed=kwargs.get('speed', True)
            )

            # 3. 🆕 根据speed参数选择执行模式
            if search_request.speed:
                # 速度模式：只使用embedding搜索（阶梯筛选）
                embedding_results = await self._google_embedding_search(search_request.intent_keywords)
                confidence_paths = await self._build_speed_mode_paths(embedding_results, search_request)
            else:
                # 标准模式：Embedding Top 50 + LLM精评
                # 1. 获取Top 50 embedding候选
                embedding_top50 = await self._google_embedding_search_top50(search_request.intent_keywords)

                # 2. 用缓存补全完整路径信息
                candidate_paths = await self._enrich_embedding_results_with_cache(embedding_top50)

                # 3. LLM评估这些候选
                confidence_evaluation = await self._evaluate_path_confidence(
                    user_input, candidate_paths
                )

                # 4. 选择高置信度路径并扩展（逻辑不变）
                confidence_paths = await self._build_confidence_paths(
                    confidence_evaluation, search_request, candidate_paths
                )

                print(f"标准搜索找到 {len(confidence_paths)} 个结果")
            
            # 6. 构建响应元数据
            processing_time = (time.time() - start_time) * 1000
            if search_request.speed:
                initial_candidates = 0
            else:
                initial_candidates = len(candidate_paths) if 'candidate_paths' in locals() else 0

            metadata = IntentSearchMetadata(
                initial_candidates=initial_candidates,
                high_confidence_matches=len(confidence_paths),
                confidence_threshold=0.8,  # 固定值
                processing_time_ms=processing_time
            )
            
            return IntentSearchResponse(
                success=True,
                intent_keywords=intent_keywords,
                search_metadata=metadata,
                confidence_paths=confidence_paths,
                total_results=len(confidence_paths)
            )
            
        except Exception as e:
            return IntentSearchResponse(
                success=False,
                intent_keywords=[],
                confidence_paths=[],
                total_results=0,
                error=str(e)
            )
    
    async def _extract_intent_keywords(self, user_input: str) -> List[str]:
        """从用户输入中提取意图关键词（简化版本）"""
        
        # 直接使用用户输入作为关键词，避免额外的API调用
        # 定义停用词
        stop_words = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
                      '一个', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
        
        # 简单分词（按空格分割）
        words = user_input.split()
        
        # 过滤停用词和短词
        keywords = [word for word in words if len(word) > 1 and word not in stop_words]
        
        # 如果没有有效关键词，使用原始输入
        if not keywords:
            keywords = [user_input]
        
        return keywords[:6]  # 最多6个关键词
    
    
    async def _get_complete_paths(self) -> List[Dict[str, Any]]:
        """从JSON缓存获取所有完整路径"""
        
        try:
            from pathlib import Path
            cache_file = Path("llm_cache/chimera_cache.json")
            
            if not cache_file.exists():
                print("缓存文件不存在，请先运行同步服务生成缓存")
                return []
            
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            complete_paths = []
            
            # 直接从缓存的paths中获取路径信息
            for path_data in cache_data.get("paths", []):
                leaf_id = path_data["leaf_id"]
                leaf_page = cache_data["pages"].get(leaf_id, {})
                
                path_info = {
                    'path_string': path_data["path_string"],
                    'path_titles': path_data["path_titles"],
                    'path_ids': path_data["path_ids"],
                    'leaf_id': leaf_id,
                    'leaf_title': path_data["leaf_title"],
                    'leaf_last_edited_time': leaf_page.get("lastEditedTime", ""),
                    'leaf_tags': leaf_page.get("tags", []),
                    'leaf_url': leaf_page.get("url", ""),
                    'path_length': path_data["path_length"],
                    'path_type': 'complete_path' if path_data["path_length"] > 0 else 'single_leaf',
                    'relevance_score': 1.0
                }
                complete_paths.append(path_info)
            
            print(f"从缓存加载了 {len(complete_paths)} 条路径")
            return complete_paths
                
        except Exception as e:
            print(f"从缓存获取路径失败: {e}")
            return []
    
    async def _get_all_notion_pages(self) -> List[Dict[str, Any]]:
        """从Neo4j获取所有NotionPage的信息"""
        
        if not self.graphiti_client._initialized:
            await self.graphiti_client.initialize()
        
        try:
            async with self.graphiti_client._driver.session() as session:
                query = """
                MATCH (p:NotionPage)
                RETURN p.notionId as notion_id, 
                       p.title as title, 
                       p.tags as tags,
                       p.url as url,
                       p.level as level
                ORDER BY p.level DESC, p.lastEditedTime DESC
                """
                
                result = await session.run(query)
                
                pages = []
                async for record in result:
                    pages.append({
                        'notion_id': record['notion_id'],
                        'title': record['title'] or 'Untitled',
                        'tags': record['tags'] or [],
                        'url': record['url'] or '',
                        'level': record['level'] or 0
                    })
                
                return pages
                
        except Exception as e:
            print(f"获取NotionPage列表失败: {e}")
            return []
    
    async def _evaluate_path_confidence(
        self, 
        user_input: str, 
        candidate_paths: List[Dict[str, Any]]
    ) -> ConfidenceEvaluationResponse:
        """使用Gemini评估路径置信度"""
        
        if not candidate_paths:
            return ConfidenceEvaluationResponse(
                evaluations=[],
                summary={
                    'total_candidates': 0,
                    'high_confidence_count': 0,
                    'threshold_used': 0.8
                }
            )
        
        # 构建评估prompt
        evaluation_prompt = self.intent_prompt.create_evaluation_prompt(
            user_input=user_input,
            candidate_paths=candidate_paths
        )
        
        try:
            # 调用Gemini进行评估
            gemini_response = await self._call_gemini(evaluation_prompt)
            
            if not gemini_response.success or not gemini_response.content:
                raise ValueError(f"Gemini API调用失败: {gemini_response.error}")
            
            # 清理响应内容，移除可能的markdown格式
            content = gemini_response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # 验证内容不为空
            if not content:
                raise ValueError("Gemini返回的内容为空")
            
            # 解析JSON响应（增强错误处理）
            try:
                evaluation_data = json.loads(content)
                if not isinstance(evaluation_data, dict):
                    raise ValueError("JSON解析结果不是字典类型")
                return ConfidenceEvaluationResponse(**evaluation_data)
            except json.JSONDecodeError as json_err:
                print(f"JSON解析错误: {json_err}")
                print(f"原始响应内容: {repr(content)}")
                raise ValueError(f"无法解析JSON响应: {json_err}")
            except (TypeError, ValueError) as model_err:
                print(f"模型构建错误: {model_err}")
                print(f"解析后的数据: {evaluation_data if 'evaluation_data' in locals() else 'N/A'}")
                raise ValueError(f"无法构建响应模型: {model_err}")
            
        except Exception as e:
            print(f"Gemini评估失败: {e}")
            print(f"错误类型: {type(e).__name__}")
            if hasattr(e, '__traceback__'):
                import traceback
                print(f"错误堆栈: {traceback.format_exc()}")
            
            # 返回默认评估（所有路径都是中等置信度）
            default_evaluations = [
                {
                    'document_index': i,
                    'confidence_score': 0.5,
                    'reasoning': f'自动评估失败，使用默认置信度。错误: {str(e)[:100]}'
                }
                for i in range(len(candidate_paths))
            ]
            
            return ConfidenceEvaluationResponse(
                evaluations=default_evaluations,
                summary={
                    'total_candidates': len(candidate_paths),
                    'high_confidence_count': 0,
                    'threshold_used': 0.7
                }
            )
    
    async def _build_confidence_paths(
        self, 
        evaluation: ConfidenceEvaluationResponse,
        request: IntentSearchRequest,
        candidate_paths: List[Dict[str, Any]]
    ) -> List[ConfidencePath]:
        """构建高置信度路径及其相关页面"""
        
        confidence_paths = []
        
        # 筛选高置信度评估 (固定阈值0.8)
        high_confidence_evals = [
            eval_item for eval_item in evaluation.evaluations
            if self._get_confidence_score(eval_item) >= 0.8
        ]
        
        # 按置信度排序，不限制数量（让client的search_results控制）
        high_confidence_evals.sort(
            key=lambda x: self._get_confidence_score(x),
            reverse=True
        )
        
        for eval_item in high_confidence_evals:
            try:
                # 获取核心页面内容
                core_page = await self._build_core_page_result(
                    eval_item, request, candidate_paths
                )
                
                # 获取相关页面 (固定深度2)
                related_pages = await self._expand_related_pages(
                    core_page.notion_id, 2
                )
                
                # 构建路径元数据
                path_metadata = ConfidencePathMetadata(
                    total_pages=1 + len(related_pages),
                    confidence_level=self._get_confidence_level(self._get_confidence_score(eval_item)),
                    expansion_depth=2  # 固定深度
                )
                
                confidence_path = ConfidencePath(
                    core_page=core_page,
                    related_pages=related_pages,
                    path_metadata=path_metadata
                )
                
                confidence_paths.append(confidence_path)
                
            except Exception as e:
                print(f"构建置信度路径时出错: {e}")
                continue

        # 直接返回LLM筛选的高置信度路径（Top 30模式下不需要额外合并）
        # 按max_results限制返回数量
        if len(confidence_paths) > request.max_results:
            confidence_paths = confidence_paths[:request.max_results]

        return confidence_paths

    async def _create_embedding_confidence_path(self, embedding_result: Dict[str, Any], request: IntentSearchRequest) -> ConfidencePath:
        """将embedding搜索结果转换为ConfidencePath（速度模式专用）"""

        try:
            page_id = embedding_result['leaf_id']
            page_title = embedding_result['leaf_title']
            page_url = embedding_result.get('leaf_url', '')
            semantic_score = embedding_result['semantic_score']

            # 获取页面内容
            from utils.page_content_fetcher import get_page_content_for_intent_search
            page_content, latest_timestamp, metadata = await get_page_content_for_intent_search(
                page_id=page_id,
                is_core_page=True,
                max_length=8000
            )

            # 使用embedding搜索中返回的完整路径信息
            path_string = embedding_result.get('path_string', page_title)
            path_titles = embedding_result.get('path_titles', [page_title])
            path_ids = embedding_result.get('path_ids', [page_id])

            # 创建CorePageResult
            core_page = CorePageResult(
                notion_id=page_id,
                title=page_title,
                url=page_url,
                tags=[],
                content=page_content,
                confidence_score=semantic_score,
                path_string=path_string,
                path_titles=path_titles,
                path_ids=path_ids,
                last_edited_time=latest_timestamp
            )

            # 标记来源和语义得分
            core_page.search_source = 'embedding'
            core_page.semantic_score = semantic_score

            # 创建路径元数据
            path_metadata = ConfidencePathMetadata(
                total_pages=1,
                confidence_level='high' if semantic_score >= 0.8 else 'medium',
                expansion_depth=0
            )

            return ConfidencePath(
                core_page=core_page,
                related_pages=[],
                path_metadata=path_metadata
            )

        except Exception as e:
            print(f"转换embedding结果失败: {e}")
            return None

    async def _build_core_page_result(
        self, 
        eval_item, 
        request: IntentSearchRequest,
        candidate_paths: List[Dict[str, Any]]
    ) -> CorePageResult:
        """构建核心页面结果"""
        
        # 从候选路径中获取对应的叶子节点信息
        document_index = self._get_document_index(eval_item)
        if document_index < len(candidate_paths):
            path_info = candidate_paths[document_index]
            page_id = path_info.get('leaf_id', '')  # 使用叶子节点ID
            page_title = path_info.get('leaf_title', 'Unknown')
            page_tags = path_info.get('leaf_tags', [])
            page_url = path_info.get('leaf_url', '')
            # 获取完整路径信息
            path_string = path_info.get('path_string', '')
            path_titles = path_info.get('path_titles', [])
            path_ids = path_info.get('path_ids', [])
            # 获取时间信息
            last_edited_time = path_info.get('leaf_last_edited_time', '')
        else:
            # 备用方案
            page_id = f"dummy_page_{document_index}"
            page_title = f"页面 {document_index}"
            page_tags = []
            page_url = ''
            path_string = ''
            path_titles = []
            path_ids = []
            last_edited_time = ''
        
        # 使用统一的页面内容获取器（包含表格和文档处理）
        try:
            page_content, latest_timestamp, metadata = await get_page_content_for_intent_search(
                page_id=page_id,
                is_core_page=True,
                max_length=8000
            )
            
            return CorePageResult(
                notion_id=page_id,
                title=page_title,
                url=page_url,
                tags=page_tags,
                content=page_content,
                confidence_score=self._get_confidence_score(eval_item),
                path_string=path_string,
                path_titles=path_titles,
                path_ids=path_ids,
                last_edited_time=latest_timestamp  # 使用实时时间戳
            )
            
        except Exception as e:
            # 如果获取失败，返回基础信息
            return CorePageResult(
                notion_id=page_id,
                title=f"页面 {document_index}",
                url='',
                tags=[],
                content=f"获取内容失败: {e}",
                confidence_score=self._get_confidence_score(eval_item),
                path_string=path_string,
                path_titles=path_titles,
                path_ids=path_ids,
                last_edited_time=last_edited_time
            )
    
    async def _expand_related_pages(
        self, 
        core_page_id: str, 
        depth: int
    ) -> List[RelatedPageResult]:
        """扩展相关页面"""
        
        related_pages = []
        
        try:
            # 使用Graphiti的expand功能
            expanded_results = await self.graphiti_client.expand(
                page_ids=[core_page_id],
                depth=depth
            )
            
            for result in expanded_results:
                # 使用统一的页面内容获取器（包含表格和文档处理）
                page_content, _, metadata = await get_page_content_for_intent_search(
                    page_id=result.get('page_id'),
                    is_core_page=False,
                    max_length=6000
                )
                
                related_page = RelatedPageResult(
                    page_id=result.get('page_id'),
                    title=result.get('title', 'Unknown'),
                    url=result.get('url', ''),
                    content=page_content,
                    depth=result.get('depth', 1),
                    relationship_path=result.get('path', [])
                )
                
                related_pages.append(related_page)
                
        except Exception as e:
            print(f"扩展相关页面时出错: {e}")
        
        return related_pages
    
    async def _call_gemini(self, prompt: str) -> GeminiAPIResponse:
        """调用Gemini API"""
        
        request = GeminiAPIRequest(prompt=prompt)
        
        try:
            # 同步调用Gemini API（异步版本可能有问题）
            response = self.gemini_model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=request.temperature,
                    max_output_tokens=request.max_output_tokens,
                    response_mime_type="application/json"  # 确保返回JSON格式
                )
            )
            
            # 检查响应
            if not response or not response.text:
                return GeminiAPIResponse(
                    success=False,
                    error="Gemini返回空响应"
                )
            
            usage_info = {}
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage_info = {
                    'prompt_tokens': getattr(response.usage_metadata, 'prompt_token_count', 0),
                    'completion_tokens': getattr(response.usage_metadata, 'candidates_token_count', 0),
                    'total_tokens': getattr(response.usage_metadata, 'total_token_count', 0)
                }
            
            return GeminiAPIResponse(
                success=True,
                content=response.text,
                usage_info=usage_info
            )
            
        except Exception as e:
            return GeminiAPIResponse(
                success=False,
                error=str(e)
            )
    
    @staticmethod
    def _get_confidence_score(eval_item) -> float:
        """从评估项中获取置信度分数，兼容dict和对象格式"""
        if isinstance(eval_item, dict):
            return eval_item.get('confidence_score', 0.0)
        else:
            return getattr(eval_item, 'confidence_score', 0.0)
    
    @staticmethod
    def _get_document_index(eval_item) -> int:
        """从评估项中获取文档索引，兼容dict和对象格式"""
        if isinstance(eval_item, dict):
            return eval_item.get('document_index', 0)
        else:
            return getattr(eval_item, 'document_index', 0)
    
    @staticmethod
    def _get_confidence_level(score: float) -> str:
        """获取置信度级别描述"""
        if score >= 0.9:
            return "极高"
        elif score >= 0.8:
            return "高"
        elif score >= 0.7:
            return "中高"
        elif score >= 0.6:
            return "中等"
        else:
            return "低"


    async def _google_embedding_search_top50(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """标准模式专用：返回Top 30语义相似的leaf节点（无阶梯筛选）"""

        embedding_results = []

        try:
            # 1. 为搜索关键词生成embedding
            search_text = ' '.join(keywords)
            search_embedding = await self.embedding_service.get_embedding(search_text)

            if not search_embedding:
                print("生成搜索embedding失败，跳过embedding搜索")
                return []

            # 2. 使用embedding搜索服务
            await self.embedding_search_service.initialize()
            search_results = await self.embedding_search_service.search_similar_pages(
                query_text=search_text,
                limit=30,              # 直接获取Top 30
                similarity_threshold=0.5  # 保持合理阈值
            )

            # 3. 转换为统一格式（无阶梯筛选，直接返回所有结果）
            for result in search_results:
                embedding_results.append({
                    'leaf_id': result['notionId'],
                    'leaf_title': result['title'],
                    'leaf_url': result.get('url', ''),
                    'semantic_score': result['score']
                })
            # print(embedding_results)
            # print(f"🔍 标准模式Embedding搜索: 找到 {len(embedding_results)} 个候选（Top 30）")

        except Exception as e:
            print(f"Embedding Top 50搜索失败: {e}")

        return embedding_results

    async def _google_embedding_search(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """速度模式专用：使用阶梯筛选的Google embedding搜索"""

        embedding_results = []

        try:
            # 1. 为搜索关键词生成embedding
            search_text = ' '.join(keywords)
            search_embedding = await self.embedding_service.get_embedding(search_text)

            if not search_embedding:
                print("生成搜索embedding失败，跳过embedding搜索")
                return []

            # 2. 使用新的embedding搜索服务
            await self.embedding_search_service.initialize()
            search_results = await self.embedding_search_service.search_similar_pages(
                query_text=search_text,
                limit=20,  # 多搜索一些候选
                similarity_threshold=0.5  # 低阈值搜索更多候选
            )
            # 3. 筛选高质量结果：Top-P阶梯式筛选（加快速度）
            # 搜索结果已按score从高到低排序
            # 策略：类似top-P采样，严格匹配阈值，没有达标返回空

            QUALITY_TIERS = [
                {'threshold': 0.98, 'target_count': 1, 'name': 'perfect'},      # 完美匹配
                {'threshold': 0.95, 'target_count': 2, 'name': 'excellent'},    # 优秀
                {'threshold': 0.90, 'target_count': 3, 'name': 'high'},         # 高质量
                {'threshold': 0.83, 'target_count': 4, 'name': 'good'},         # 良好
            ]

            high_quality_results = []

            # 遍历每个质量层级，找到第一个满足条件的层级
            for tier in QUALITY_TIERS:
                candidates = [r for r in search_results if r['score'] >= tier['threshold']]

                if len(candidates) >= tier['target_count']:
                    # 找到足够数量的高质量结果
                    high_quality_results = candidates[:tier['target_count']]
                    # print(f"✅ Embedding筛选: {tier['name']}级 | {len(high_quality_results)}个结果 | 阈值≥{tier['threshold']}")
                    break

            # 如果所有层级都不满足，返回空（严格模式）
            if not high_quality_results:
                print(f"Embedding筛选: 未达标，返回空结果")

            # 4. 转换为统一格式 - 只使用高质量结果
            for result in high_quality_results:
                embedding_results.append({
                    'leaf_id': result['notionId'],  # 新格式使用'notionId'
                    'leaf_title': result['title'],
                    'path_string': result['title'],  # 暂时使用title作为path_string
                    'path_titles': [result['title']],  # 暂时使用title作为path_titles
                    'path_ids': [result['notionId']],  # 暂时使用notionId作为path_ids
                    'leaf_last_edited_time': '',  # 从embedding搜索中暂时没有这个信息
                    'leaf_tags': [],  # 从embedding搜索中暂时没有这个信息
                    'leaf_url': result.get('url', ''),
                    'path_length': 0,  # 暂时设为0，因为是单个页面
                    'path_type': 'embedding_search',
                    'semantic_score': result['score'],  # 新格式使用'score'字段
                    'embedding_text': '',  # 新格式暂时没有这个信息
                    'search_source': 'google_embedding'
                })


        except Exception as e:
            print(f"Google embedding搜索时出错: {e}")

        return embedding_results

    async def _enrich_embedding_results_with_cache(self, embedding_results: List[Dict]) -> List[Dict[str, Any]]:
        """将embedding的Top 50结果补全为完整路径信息"""

        from pathlib import Path
        cache_file = Path("llm_cache/chimera_cache.json")

        if not cache_file.exists():
            print("⚠️ 缓存文件不存在，无法enrichment")
            return []

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            enriched_paths = []

            for emb_result in embedding_results:
                leaf_id = emb_result['leaf_id']

                # 从缓存中查找完整路径
                for path_data in cache_data.get("paths", []):
                    if path_data["leaf_id"] == leaf_id:
                        leaf_page = cache_data["pages"].get(leaf_id, {})

                        enriched = {
                            'path_string': path_data["path_string"],
                            'path_titles': path_data["path_titles"],
                            'path_ids': path_data["path_ids"],
                            'leaf_id': leaf_id,
                            'leaf_title': path_data["leaf_title"],
                            'leaf_last_edited_time': leaf_page.get("lastEditedTime", ""),
                            'leaf_tags': leaf_page.get("tags", []),
                            'leaf_url': leaf_page.get("url", ""),
                            'path_length': path_data["path_length"],
                            'path_type': 'embedding_candidate',
                            'semantic_score': emb_result['semantic_score'],
                            'relevance_score': emb_result['semantic_score']  # 兼容性字段
                        }
                        enriched_paths.append(enriched)
                        break
            #
            # print(f"✅ 缓存enrichment完成: {len(enriched_paths)}/{len(embedding_results)} 个候选")
            return enriched_paths

        except Exception as e:
            print(f"❌ Enrichment失败: {e}")
            return []

    async def _build_speed_mode_paths(self, embedding_results: List[Dict[str, Any]], request: IntentSearchRequest) -> List[ConfidencePath]:
        """
        速度模式：只使用embedding搜索结果构建路径

        Args:
            embedding_results: embedding搜索结果
            request: 搜索请求

        Returns:
            构建的置信度路径列表
        """
        print(f"速度模式：只使用embedding搜索，找到 {len(embedding_results)} 个结果")

        confidence_paths = []

        try:
            # 对embedding结果按相似度排序
            sorted_results = sorted(embedding_results, key=lambda x: x['semantic_score'], reverse=True)

            # 应用max_results限制
            limited_results = sorted_results[:request.max_results]

            for embedding_result in limited_results:
                embedding_path = await self._create_embedding_confidence_path(embedding_result, request)
                if embedding_path:
                    # 标记为速度模式结果
                    embedding_path.core_page.search_source = 'speed_mode_embedding'
                    confidence_paths.append(embedding_path)
                    print(f"⚡ 速度模式结果: {embedding_path.core_page.title} (相似度: {embedding_path.core_page.confidence_score:.4f})")

            print(f"⚡ 速度模式完成，返回 {len(confidence_paths)} 个结果")
            return confidence_paths

        except Exception as e:
            print(f"速度模式构建路径失败: {e}")
            return []


    async def search_only(
        self,
        query: str,
        speed: bool = True,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        仅执行搜索，返回页面ID列表和基础元数据（不获取完整内容）

        这是GPT MCP标准search工具的核心方法，复用现有search_by_intent逻辑。

        Args:
            query: 搜索查询字符串
            speed: 速度模式（True=仅embedding，False=混合搜索）
            max_results: 最大返回结果数

        Returns:
            List[Dict] with keys: id, title, url
            例如: [
                {"id": "page-id-1", "title": "页面标题1", "url": "https://..."},
                {"id": "page-id-2", "title": "页面标题2", "url": "https://..."}
            ]
        """
        try:
            # 复用现有search_by_intent逻辑
            result = await self.search_by_intent(query, speed=speed, max_results=max_results)

            search_results = []
            if result.success and result.confidence_paths:
                for path in result.confidence_paths:
                    search_results.append({
                        'id': path.core_page.notion_id,
                        'title': path.core_page.title,
                        'url': path.core_page.url
                    })

            print(f"✅ search_only完成，找到 {len(search_results)} 个结果")
            return search_results

        except Exception as e:
            print(f"❌ search_only失败: {e}")
            return []

    async def fetch_by_ids(
        self,
        page_ids: List[str],
        include_children: bool = False
    ) -> List[Dict[str, Any]]:
        """
        根据页面ID列表并发获取完整路径的所有页面内容

        这是GPT MCP标准fetch工具的核心方法，会获取每个ID的完整路径上所有页面的内容。

        Args:
            page_ids: 要获取的叶子页面ID列表
            include_children: 是否包含子页面（暂未实现）

        Returns:
            List[Dict] with keys: id, title, text, url, metadata, path_info
            例如: [
                {
                    "id": "leaf-page-id",
                    "title": "叶子页面标题",
                    "text": "叶子页面完整内容...",
                    "url": "https://...",
                    "metadata": {
                        "last_edited_time": "...",
                        "path_string": "Root -> Parent -> Leaf",
                        "path_contents": [
                            {"title": "Root", "content": "...", "position": 0},
                            {"title": "Parent", "content": "...", "position": 1},
                            {"title": "Leaf", "content": "...", "position": 2}
                        ]
                    }
                }
            ]
        """
        try:
            # 首先需要获取每个page_id的完整路径信息
            # 从缓存或搜索结果中获取路径信息
            fetch_results = []

            for page_id in page_ids:
                try:
                    # 1. 获取叶子页面的路径信息（从缓存）
                    path_info = await self._get_path_info_for_page(page_id)

                    if not path_info:
                        # 如果缓存中没有，只获取单个页面
                        print(f"⚠️ 页面 {page_id} 没有找到路径信息，只获取单页内容")
                        single_result = await self._fetch_single_page(page_id)
                        if single_result:
                            fetch_results.append(single_result)
                        continue

                    # 2. 获取路径上所有页面的内容
                    path_ids = path_info.get('path_ids', [page_id])
                    path_titles = path_info.get('path_titles', [path_info.get('title', 'Unknown')])
                    path_string = path_info.get('path_string', path_info.get('title', 'Unknown'))

                    # 3. 并发获取路径上所有页面的内容
                    from utils.page_content_fetcher import PageContentFetcher
                    fetcher = PageContentFetcher(self.notion_client)

                    path_page_results = await fetcher.get_multiple_pages_content(
                        page_ids=path_ids,
                        config={
                            'include_files': True,
                            'include_tables': True,
                            'max_content_length': 10000
                        },
                        purpose='fetch_tool_with_path'
                    )

                    # 4. 构建路径内容数组
                    path_contents = []
                    for i, (pid, ptitle) in enumerate(zip(path_ids, path_titles)):
                        # 找到对应的内容
                        page_content = ""
                        last_edited_time = ""
                        for page_result in path_page_results:
                            if page_result['page_id'] == pid:
                                if page_result['success']:
                                    page_content = page_result['content']
                                    last_edited_time = page_result['timestamp']
                                else:
                                    page_content = f"📄 路径页面: {ptitle} (内容获取失败)"
                                break

                        if not page_content and pid != page_id:
                            # 不是叶子节点且没有内容，使用占位符
                            page_content = f"📄 路径页面: {ptitle}"

                        path_contents.append({
                            "position": i,
                            "title": ptitle,
                            "notion_id": pid,
                            "content": page_content,
                            "content_length": len(page_content),
                            "last_edited_time": last_edited_time,
                            "is_leaf": (pid == page_id)
                        })

                    # 5. 找到叶子页面的完整内容（作为主内容）
                    leaf_content = ""
                    leaf_url = path_info.get('url', '')
                    leaf_last_edited = path_info.get('last_edited_time', '')

                    for content_item in path_contents:
                        if content_item['is_leaf']:
                            leaf_content = content_item['content']
                            leaf_last_edited = content_item['last_edited_time']
                            break

                    # 6. 构建fetch结果
                    fetch_results.append({
                        'id': page_id,
                        'title': path_info.get('title', 'Unknown'),
                        'text': leaf_content,
                        'url': leaf_url,
                        'metadata': {
                            'last_edited_time': leaf_last_edited,
                            'content_length': len(leaf_content),
                            'path_string': path_string,
                            'path_contents': path_contents,
                            'total_path_pages': len(path_contents)
                        }
                    })

                except Exception as e:
                    print(f"❌ 获取页面 {page_id} 路径内容失败: {e}")
                    # 尝试只获取单页内容作为降级
                    single_result = await self._fetch_single_page(page_id)
                    if single_result:
                        fetch_results.append(single_result)

            print(f"✅ fetch_by_ids完成，成功获取 {len(fetch_results)} / {len(page_ids)} 个页面及其路径内容")
            return fetch_results

        except Exception as e:
            print(f"❌ fetch_by_ids失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def _get_path_info_for_page(self, page_id: str) -> Optional[Dict[str, Any]]:
        """从缓存中获取页面的路径信息"""
        try:
            from pathlib import Path
            cache_file = Path("llm_cache/chimera_cache.json")

            if not cache_file.exists():
                return None

            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # 查找包含此page_id的路径
            for path_data in cache_data.get("paths", []):
                if path_data["leaf_id"] == page_id:
                    return {
                        'path_string': path_data["path_string"],
                        'path_ids': path_data["path_ids"],
                        'path_titles': path_data["path_titles"],
                        'title': path_data["leaf_title"],
                        'url': cache_data["pages"].get(page_id, {}).get("url", ""),
                        'last_edited_time': cache_data["pages"].get(page_id, {}).get("lastEditedTime", "")
                    }

            return None

        except Exception as e:
            print(f"⚠️ 从缓存获取路径信息失败: {e}")
            return None

    async def _fetch_single_page(self, page_id: str) -> Optional[Dict[str, Any]]:
        """获取单个页面内容（降级方案）"""
        try:
            from utils.page_content_fetcher import PageContentFetcher
            fetcher = PageContentFetcher(self.notion_client)

            content, timestamp, metadata = await fetcher.get_page_content(
                page_id=page_id,
                config={
                    'include_files': True,
                    'include_tables': True,
                    'max_content_length': 10000
                },
                purpose='fetch_tool_single'
            )

            # 获取基本信息
            normalized_id = self.notion_client._normalize_page_id(page_id)
            page_info = await self.notion_client.extractor.get_page_basic_info(normalized_id)

            return {
                'id': page_id,
                'title': page_info.get('title', 'Unknown') if page_info else 'Unknown',
                'text': content,
                'url': page_info.get('url', '') if page_info else '',
                'metadata': {
                    'last_edited_time': timestamp,
                    'content_length': len(content),
                    'path_string': page_info.get('title', 'Unknown') if page_info else 'Unknown',
                    'path_contents': [{
                        'position': 0,
                        'title': page_info.get('title', 'Unknown') if page_info else 'Unknown',
                        'notion_id': page_id,
                        'content': content,
                        'content_length': len(content),
                        'last_edited_time': timestamp,
                        'is_leaf': True
                    }],
                    'total_path_pages': 1
                }
            }

        except Exception as e:
            print(f"❌ 获取单页内容失败: {e}")
            return None


# 便利函数
async def search_user_intent(user_input: str, **kwargs) -> IntentSearchResponse:
    """
    便利函数：根据用户意图搜索
    
    Args:
        user_input: 用户输入文本
        **kwargs: 可选参数
    
    Returns:
        IntentSearchResponse: 搜索结果
    """
    engine = IntentSearchEngine()
    return await engine.search_by_intent(user_input, **kwargs)


# 示例使用
if __name__ == "__main__":
    async def test_intent_search():
        # 测试意图搜索
        result = await search_user_intent(
            "我想找关于机器学习项目的笔记",
            max_results=3,
            speed=False
        )
        
        print(f"搜索成功: {result.success}")
        print(f"意图关键词: {result.intent_keywords}")
        print(f"置信度路径数量: {len(result.confidence_paths)}")
        
        for i, path in enumerate(result.confidence_paths):
            print(f"\n路径 {i+1}:")
            print(f"  核心页面: {path.core_page.title}")
            print(f"  置信度: {path.core_page.confidence_score:.2f}")
            print(f"  相关页面数: {len(path.related_pages)}")
    
    # 运行测试
    asyncio.run(test_intent_search())