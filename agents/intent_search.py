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
                confidence_threshold=kwargs.get('confidence_threshold', 0.7),
                max_results=kwargs.get('max_results', 5),
                expansion_depth=kwargs.get('expansion_depth', 2)
            )

            # 3. 🆕 并行执行：获取候选路径 + embedding搜索
            candidate_paths_task = self._get_complete_paths()
            embedding_search_task = self._google_embedding_search(search_request.intent_keywords)

            candidate_paths, embedding_results = await asyncio.gather(
                candidate_paths_task,
                embedding_search_task
            )

            # 保存embedding结果供后续使用
            self._embedding_results = embedding_results

            # 4. 使用Gemini进行路径置信度评估
            confidence_evaluation = await self._evaluate_path_confidence(
                user_input, candidate_paths
            )

            # 5. 选择高置信度路径并扩展
            confidence_paths = await self._build_confidence_paths(
                confidence_evaluation, search_request, candidate_paths
            )
            
            # 6. 构建响应元数据
            processing_time = (time.time() - start_time) * 1000
            metadata = IntentSearchMetadata(
                initial_candidates=len(candidate_paths),
                high_confidence_matches=len(confidence_paths),
                confidence_threshold=search_request.confidence_threshold,
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
        
        return keywords[:5]  # 最多5个关键词
    
    
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
                    'threshold_used': 0.7
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
        
        # 筛选高置信度评估
        high_confidence_evals = [
            eval_item for eval_item in evaluation.evaluations
            if self._get_confidence_score(eval_item) >= request.confidence_threshold
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
                
                # 获取相关页面
                related_pages = await self._expand_related_pages(
                    core_page.notion_id, request.expansion_depth
                )
                
                # 构建路径元数据
                path_metadata = ConfidencePathMetadata(
                    total_pages=1 + len(related_pages),
                    confidence_level=self._get_confidence_level(self._get_confidence_score(eval_item)),
                    expansion_depth=request.expansion_depth
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

        # 🆕 智能混合搜索：合并embedding结果
        final_paths = await self._smart_merge_with_embedding_results(confidence_paths, request)

        return final_paths

    async def _smart_merge_with_embedding_results(self, llm_paths: List[ConfidencePath], request: IntentSearchRequest) -> List[ConfidencePath]:
        """混合搜素：LLM结果 + Embedding top3，去重后返回"""

        if not hasattr(self, '_embedding_results') or not self._embedding_results:
            print("无embedding搜索结果，返回LLM判断结果")
            return llm_paths

        try:

            # 1. 先添加所有LLM结果
            final_results = []
            llm_page_ids = set()

            for path in llm_paths:
                print(f"LLM判断结果: {path.core_page.title} (置信度: {path.core_page.confidence_score:.4f})")
                final_results.append(path)
                llm_page_ids.add(path.core_page.notion_id)
                path.core_page.search_source = 'llm_judgment'

            # 2. 添加embedding结果（去重）
            embedding_added = 0
            for embedding_result in self._embedding_results:
                page_id = embedding_result['leaf_id']
                if page_id not in llm_page_ids:  # 去重
                    embedding_path = await self._create_embedding_confidence_path(embedding_result, request)
                    if embedding_path:
                        final_results.append(embedding_path)
                        embedding_added += 1

            # 3. 应用max_results限制
            if len(final_results) > request.max_results:
                # 按置信度排序，取top N
                final_results.sort(key=lambda x: x.core_page.confidence_score, reverse=True)
                final_results = final_results[:request.max_results]
            # print(final_results)
            return final_results

        except Exception as e:
            print(f"合并出错: {e}，返回LLM结果")
            return llm_paths


    async def _create_embedding_confidence_path(self, embedding_result: Dict[str, Any], request: IntentSearchRequest) -> ConfidencePath:
        """将embedding搜索结果转换为ConfidencePath"""

        try:
            page_id = embedding_result['leaf_id']  # 修正：使用leaf_id
            page_title = embedding_result['leaf_title']  # 修正：使用leaf_title
            page_url = embedding_result.get('leaf_url', '')  # 修正：使用leaf_url
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
                confidence_score=semantic_score,  # 使用语义相似度作为置信度
                path_string=path_string,  # 使用完整路径信息
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
                expansion_depth=0  # embedding结果不做扩展
            )

            return ConfidencePath(
                core_page=core_page,
                related_pages=[],  # embedding结果不扩展相关页面，保持简洁
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


    async def _google_embedding_search(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """使用Google embedding进行语义搜索"""

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
            # 3. 筛选高质量结果：只保留相似度 > 0.75 的top3
            high_quality_results = [
                result for result in search_results
                if result['score'] > 0.8
            ][:3]  # 取top3

            # 4. 转换为统一格式 - 只使用高质量结果
            for result in high_quality_results:
                print(f"Embedding top结果: {result['title']} (相似度: {result['score']:.4f})")
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
            confidence_threshold=0.6,
            max_results=3,
            expansion_depth=2
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