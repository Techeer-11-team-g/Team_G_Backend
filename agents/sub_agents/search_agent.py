"""
AI 패션 어시스턴트 - 검색 에이전트
기존 분석 파이프라인과 Refine 기능을 활용한 검색 처리
"""

import logging
import base64
from typing import Dict, Any, Optional, List

from django.core.files.uploadedfile import InMemoryUploadedFile

from services import (
    get_embedding_service,
    get_redis_service,
)
from services.opensearch_client import OpenSearchService
from agents.response_builder import ResponseBuilder
from config.tracing import traced, get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


class SearchAgent:
    """
    검색 에이전트 - 기존 분석 파이프라인 활용

    핵심 연동 포인트:
    - 이미지 검색: 기존 process_image_analysis 활용
    - 텍스트 검색: OpenSearchService 직접 활용
    - Refine: 기존 parse_refine_query_task 활용 (핵심!)
    """

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.opensearch = OpenSearchService()
        self.embedding_service = get_embedding_service()
        self.redis = get_redis_service()

    @traced("search_agent.handle")
    def handle(
        self,
        sub_intent: str,
        message: str,
        image: Optional[bytes],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """검색 요청 처리"""
        try:
            if sub_intent == 'new_search':
                if image:
                    return self.image_search(image, message, context)
                else:
                    return self.text_search(message, context)

            elif sub_intent == 'refine':
                return self.refine_search(message, context)

            elif sub_intent == 'similar':
                return self.similar_search(context)

            elif sub_intent == 'cross_recommend':
                return self.cross_category_search(message, image, context)

            else:
                return self.text_search(message, context)

        except Exception as e:
            logger.error(f"SearchAgent error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "search_error",
                "검색 중 문제가 발생했어요. 다시 시도해주세요."
            )

    @traced("search_agent.image_search")
    def image_search(
        self,
        image: bytes,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        이미지 기반 검색 - 기존 분석 파이프라인 활용

        1. 이미지 업로드 (UploadedImage 생성)
        2. 분석 시작 (ImageAnalysis 생성)
        3. Celery Task 실행 (process_image_analysis)
        4. 결과 반환 (폴링 또는 대기)
        """
        from analyses.models import UploadedImage, ImageAnalysis
        from analyses.tasks.analysis import process_image_analysis
        from django.core.files.base import ContentFile
        import uuid

        try:
            # 1. 이미지 업로드
            uploaded_image = UploadedImage.objects.create(
                user_id=self.user_id,
                uploaded_image_url=""  # GCS 업로드 후 업데이트
            )

            # 2. 분석 시작
            analysis = ImageAnalysis.objects.create(
                uploaded_image=uploaded_image,
                image_analysis_status='PENDING'
            )

            # 3. Celery Task 실행 (Base64로 전달하여 빠른 처리)
            image_b64 = base64.b64encode(image).decode('utf-8')
            process_image_analysis.delay(
                analysis_id=analysis.id,
                image_url=None,
                user_id=self.user_id,
                image_b64=image_b64
            )

            # 4. 컨텍스트 업데이트
            context['current_analysis_id'] = analysis.id
            context['analysis_pending'] = True

            return ResponseBuilder.analysis_pending(analysis.id)

        except Exception as e:
            logger.error(f"Image search error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "upload_error",
                "이미지 처리 중 문제가 발생했어요. 다시 시도해주세요."
            )

    @traced("search_agent.text_search")
    def text_search(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        텍스트 기반 검색 - OpenSearch 직접 활용

        1. 검색 조건 파싱
        2. 텍스트 임베딩 생성
        3. OpenSearch 하이브리드 검색
        """
        try:
            # 1. 검색 조건 추출 (컨텍스트에서)
            search_params = context.get('intent_result', {}).get('search_params', {})

            # 2. 텍스트 임베딩 생성
            text_embedding = self.embedding_service.get_text_embedding(message)

            # 3. 카테고리 결정
            categories = search_params.get('target_categories', [])
            category = categories[0] if categories else None

            # 4. OpenSearch 검색
            results = self.opensearch.search_similar_products_hybrid(
                embedding=text_embedding,
                category=category or 'top',  # 기본 카테고리
                k=30
            )

            if not results:
                return ResponseBuilder.no_results(
                    "조건에 맞는 상품을 찾지 못했어요. 조건을 바꿔서 다시 찾아볼까요?"
                )

            # 5. 결과 정규화 및 컨텍스트 업데이트
            normalized_results = self._normalize_search_results(results[:5])
            context['search_results'] = normalized_results
            context['has_search_results'] = True
            context['search_filters'] = search_params

            return ResponseBuilder.search_results(
                normalized_results,
                f"'{message}'로 검색한 결과예요:",
                search_params.get('understood_intent')
            )

        except Exception as e:
            logger.error(f"Text search error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "search_error",
                "검색 중 문제가 발생했어요. 다시 시도해주세요."
            )

    @traced("search_agent.refine_search")
    def refine_search(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        자연어 재분석 - 기존 parse_refine_query 활용 (핵심!)

        기존 LangChainService의 parse_refine_query_v2를 활용하여
        대화 이력 기반 검색 조건 파싱
        """
        analysis_id = context.get('current_analysis_id')

        if not analysis_id:
            # 분석 컨텍스트 없으면 텍스트 검색으로 전환
            return self.text_search(message, context)

        try:
            # 기존 parse_refine_query_task 활용!
            from analyses.tasks.refine import parse_refine_query_task

            # Celery Task 실행 (동기 대기)
            result = parse_refine_query_task.apply(
                args=[
                    message,
                    ['top', 'bottom', 'outer', 'shoes', 'bag', 'hat', 'skirt'],
                    analysis_id,
                    True  # use_v2
                ]
            ).get(timeout=30)

            # 결과 가져오기
            from analyses.models import ObjectProductMapping

            mappings = list(ObjectProductMapping.objects.filter(
                detected_object__uploaded_image__analyses__id=analysis_id,
                is_deleted=False
            ).select_related(
                'product'
            ).order_by('-confidence_score')[:5])

            products = [self._mapping_to_product(m) for m in mappings]

            if not products:
                return ResponseBuilder.no_results(
                    f"'{message}' 조건에 맞는 상품을 찾지 못했어요."
                )

            # 컨텍스트 업데이트
            context['search_results'] = products
            context['has_search_results'] = True

            return ResponseBuilder.search_results(
                products,
                f"'{message}' 조건으로 다시 찾았어요:"
            )

        except Exception as e:
            logger.error(f"Refine search error: {e}", exc_info=True)
            # 폴백: 텍스트 검색으로 전환
            return self.text_search(message, context)

    @traced("search_agent.similar_search")
    def similar_search(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """현재 선택 상품과 유사한 상품 검색"""
        selected = context.get('selected_product')
        if not selected:
            results = context.get('search_results', [])
            if results:
                selected = results[0]
            else:
                return ResponseBuilder.ask_search_first()

        try:
            # 선택 상품의 임베딩으로 유사 검색
            from products.models import Product

            product = Product.objects.get(id=selected.get('product_id'))

            # 상품의 임베딩으로 유사 상품 검색
            # 기존 상품의 이미지로 임베딩 생성하거나 저장된 임베딩 사용
            text_query = f"{product.brand_name} {product.product_name}"
            embedding = self.embedding_service.get_text_embedding(text_query)

            results = self.opensearch.search_similar_products_hybrid(
                embedding=embedding,
                category=product.category,
                k=10
            )

            # 선택 상품 제외 및 정규화
            results = [r for r in results if r.get('product_id') != product.id]
            normalized_results = self._normalize_search_results(results[:5])

            if not normalized_results:
                return ResponseBuilder.no_results("비슷한 상품을 찾지 못했어요.")

            context['search_results'] = normalized_results
            context['has_search_results'] = True

            return ResponseBuilder.search_results(
                normalized_results,
                f"{selected.get('product_name', '선택한 상품')}과 비슷한 상품이에요:"
            )

        except Exception as e:
            logger.error(f"Similar search error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "search_error",
                "비슷한 상품을 찾는 중 문제가 발생했어요."
            )

    @traced("search_agent.cross_category_search")
    def cross_category_search(
        self,
        message: str,
        image: Optional[bytes],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        크로스 카테고리 추천
        예: 셔츠 이미지 + "어울리는 바지 찾아줘"
        """
        try:
            # 이미지가 있으면 먼저 분석
            if image:
                # 이미지 분석하여 속성 추출
                from services import get_gpt4v_service
                gpt4v = get_gpt4v_service()

                # Base64 인코딩
                image_b64 = base64.b64encode(image).decode('utf-8')

                # 속성 추출 (간소화)
                attributes = {
                    "color": "white",  # 실제로는 Claude Vision으로 추출
                    "style": "casual"
                }

                context['source_attributes'] = attributes

            # 대상 카테고리 추출
            search_params = context.get('intent_result', {}).get('search_params', {})
            target_categories = search_params.get('target_categories', ['bottom'])

            # 크로스 카테고리 검색 - 텍스트 임베딩 사용
            text_embedding = self.embedding_service.get_text_embedding(message)
            target_category = target_categories[0] if target_categories else 'bottom'

            results = self.opensearch.search_similar_products_hybrid(
                embedding=text_embedding,
                category=target_category,
                k=30
            )

            if not results:
                return ResponseBuilder.no_results()

            # 결과 정규화 및 컨텍스트 업데이트
            normalized_results = self._normalize_search_results(results[:5])
            context['search_results'] = normalized_results
            context['has_search_results'] = True

            return ResponseBuilder.search_results(
                normalized_results,
                "어울리는 상품을 찾았어요:"
            )

        except Exception as e:
            logger.error(f"Cross category search error: {e}", exc_info=True)
            return self.text_search(message, context)

    def _mapping_to_product(self, mapping) -> Dict[str, Any]:
        """ObjectProductMapping을 product dict로 변환"""
        product = mapping.product
        return {
            'product_id': product.id,
            'brand_name': product.brand_name,
            'product_name': product.product_name,
            'selling_price': product.selling_price,
            'image_url': product.product_image_url,
            'product_url': product.product_url,
            'category': product.category,
            'confidence_score': mapping.confidence_score
        }

    def _normalize_search_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """OpenSearch 결과를 표준 포맷으로 변환"""
        normalized = []
        for r in results:
            normalized.append({
                'product_id': r.get('product_id') or r.get('itemId'),
                'brand_name': r.get('brand_name') or r.get('brand', ''),
                'product_name': r.get('product_name') or r.get('name', ''),
                'selling_price': r.get('selling_price') or r.get('price', 0),
                'image_url': r.get('image_url') or r.get('imageUrl', ''),
                'product_url': r.get('product_url') or r.get('productUrl', ''),
                'category': r.get('category', ''),
                'score': r.get('score', 0),
            })
        return normalized

    def get_analysis_results(self, analysis_id: int) -> List[Dict[str, Any]]:
        """분석 결과 조회"""
        from analyses.models import ObjectProductMapping

        mappings = ObjectProductMapping.objects.filter(
            detected_object__uploaded_image__analyses__id=analysis_id,
            is_deleted=False
        ).select_related('product').order_by('-confidence_score')[:5]

        return [self._mapping_to_product(m) for m in mappings]
