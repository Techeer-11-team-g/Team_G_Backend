"""
Refine Analysis Tasks - 자연어 기반 재분석 병렬 처리.

리팩토링:
- 상수 모듈 활용 (constants.py)
- 공통 유틸리티 활용 (utils.py)
- 장문 함수 분리 (refine_single_object → 7개 헬퍼)
- 속성 필터링 로직 일반화
"""

import logging
import numpy as np
from io import BytesIO
from typing import Optional

from celery import shared_task, chord
from PIL import Image

from services.redis_service import get_redis_service, RedisService
from services.embedding_service import get_embedding_service
from services.opensearch_client import OpenSearchService

from analyses.constants import (
    CATEGORY_MAPPING,
    SearchConfig,
)
from analyses.utils import (
    normalize_category,
    create_span,
    apply_attribute_filters,
    build_fashion_description,
    get_or_create_product_from_search,
)
from analyses.tasks.storage import download_image


logger = logging.getLogger(__name__)

# 트레이서 모듈명
TRACER_NAME = "analyses.tasks.refine"


# =============================================================================
# Main Celery Tasks
# =============================================================================

@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def parse_refine_query_task(
    self,
    query: str,
    available_categories: list[str],
    analysis_id: int = None,
    use_v2: bool = False,  # 기본값 False로 변경 - 안정성 우선
):
    """
    자연어 쿼리를 파싱하는 Celery 태스크.

    v2 (기본값):
    - Function Calling으로 구조화된 출력 보장
    - 다중 요청 파싱 지원
    - 대화 히스토리 문맥 유지

    Args:
        query: 사용자 자연어 쿼리
        available_categories: 가용 카테고리 목록
        analysis_id: 분석 ID (대화 문맥용)
        use_v2: 향상된 파싱 사용 여부 (기본: True)

    Returns:
        파싱된 쿼리 정보 dict
        v2: {'requests': [...], 'understood_intent': str, ...}
        v1: {'action': str, 'target_categories': [...], ...}
    """
    from services.langchain_service import get_langchain_service

    with create_span(TRACER_NAME, "parse_refine_query") as span:
        span.set("query", query[:100] if query else "none")
        span.set("use_v2", use_v2)

        try:
            langchain_service = get_langchain_service(temperature=0.3)

            if use_v2:
                # 대화 히스토리 로드
                conversation_history = []
                if analysis_id:
                    conversation_history = langchain_service.get_conversation_history(analysis_id)

                # Function Calling 기반 파싱
                parsed_result = langchain_service.parse_refine_query_v2(
                    query=query,
                    available_categories=available_categories,
                    conversation_history=conversation_history,
                    analysis_id=analysis_id,
                )

                logger.info(f"V2 parsed: {len(parsed_result.get('requests', []))} requests")
                logger.info(f"Intent: {parsed_result.get('understood_intent')}")

                # 하위 호환성: 단일 요청인 경우 기존 형식으로도 반환
                if len(parsed_result.get('requests', [])) == 1:
                    single_req = parsed_result['requests'][0]
                    single_req['_v2_result'] = parsed_result  # 전체 결과 참조 저장
                    return single_req

                span.set("result.requests_count", len(parsed_result.get('requests', [])))
                return parsed_result

            else:
                # 레거시 파싱
                parsed_query = langchain_service.parse_refine_query(query, available_categories)
                logger.info(f"Legacy parsed query: {parsed_query}")
                span.set("result.action", parsed_query.get('action', 'unknown'))
                return parsed_query

        except Exception as e:
            logger.error(f"Failed to parse query: {e}")
            span.set("error", str(e))
            return _get_default_parsed_query(available_categories)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def process_refine_analysis(
    self,
    refine_id: str,
    analysis_id: int,
    target_object_ids: list[int],
    parsed_query: dict,
):
    """
    자연어 기반 재분석 메인 태스크.
    Celery Group을 사용하여 여러 객체를 병렬 처리합니다.
    """
    with create_span(TRACER_NAME, "process_refine_analysis") as span:
        span.set("refine.id", refine_id)
        span.set("analysis.id", analysis_id)
        span.set("objects.count", len(target_object_ids))

        redis_service = get_redis_service()

        try:
            # 상태 업데이트: RUNNING
            redis_service.set(f"refine:{refine_id}:status", "RUNNING", ttl=RedisService.TTL_REFINE)
            redis_service.set(f"refine:{refine_id}:progress", "0", ttl=RedisService.TTL_REFINE)
            redis_service.set(f"refine:{refine_id}:total", str(len(target_object_ids)), ttl=RedisService.TTL_REFINE)

            logger.info(f"Starting refine analysis {refine_id} for {len(target_object_ids)} objects")

            # Chord 태스크에 trace context 수동 전파
            from opentelemetry.propagate import inject
            trace_headers = {}
            inject(trace_headers)

            # 각 객체별 서브태스크 생성 (trace context 포함)
            subtasks = [
                refine_single_object.s(
                    refine_id=refine_id,
                    detected_object_id=obj_id,
                    parsed_query=parsed_query,
                ).set(headers=trace_headers)
                for obj_id in target_object_ids
            ]

            # Celery Group으로 병렬 실행 (callback에도 trace context 전파)
            callback = refine_analysis_complete.s(refine_id=refine_id, analysis_id=analysis_id).set(headers=trace_headers)
            chord(subtasks)(callback)

            logger.info(f"Refine analysis {refine_id} tasks dispatched")
            span.set("status", "DISPATCHED")
            return {'refine_id': refine_id, 'status': 'DISPATCHED', 'task_count': len(subtasks)}

        except Exception as e:
            logger.error(f"Refine analysis {refine_id} failed to start: {e}")
            redis_service.set(f"refine:{refine_id}:status", "FAILED", ttl=RedisService.TTL_REFINE)
            redis_service.set(f"refine:{refine_id}:error", str(e), ttl=RedisService.TTL_REFINE)
            span.set("error", str(e))
            raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def refine_single_object(
    self,
    refine_id: str,
    detected_object_id: int,
    parsed_query: dict,
):
    """
    단일 DetectedObject에 대한 재검색 태스크.

    리팩토링: 325줄 → 메인 함수 + 7개 헬퍼 함수로 분리
    """
    from analyses.models import DetectedObject, ObjectProductMapping

    with create_span(TRACER_NAME, f"refine_single_object_{detected_object_id}") as span:
        span.set("refine.id", refine_id)
        span.set("object.id", detected_object_id)

        redis_service = get_redis_service()

        try:
            # 1. DetectedObject 조회
            detected_obj = DetectedObject.objects.get(id=detected_object_id, is_deleted=False)
            span.set("object.category", detected_obj.object_category)

            # 1-1. 기존 매핑된 상품 ID 조회 (재검색 시 제외용)
            existing_product_ids = set(
                ObjectProductMapping.objects.filter(
                    detected_object=detected_obj,
                    is_deleted=False
                ).values_list('product__product_url', flat=True)
            )
            # URL에서 product_id 추출 (예: https://www.musinsa.com/products/12345 → 12345)
            exclude_product_ids = set()
            for url in existing_product_ids:
                if url:
                    pid = url.rstrip('/').split('/')[-1]
                    exclude_product_ids.add(pid)

            if exclude_product_ids:
                logger.info(f"Excluding {len(exclude_product_ids)} existing products: {exclude_product_ids}")

            # 2. 임베딩 생성 (이미지 + 텍스트)
            image_embedding = _generate_image_embedding(detected_obj)
            text_embedding = _generate_text_embedding(parsed_query, detected_obj.object_category)

            # 3. 임베딩 결합
            embedding = _combine_embeddings(image_embedding, text_embedding, parsed_query)

            # 4. 검색 실행
            search_results = _execute_search(embedding, detected_obj.object_category)

            # 4-1. 기존 매핑 상품 제외
            if exclude_product_ids:
                before_count = len(search_results)
                search_results = [
                    r for r in search_results
                    if str(r.get('product_id', '')) not in exclude_product_ids
                ]
                logger.info(f"Excluded existing products: {before_count} → {len(search_results)}")

            # 5. 속성 필터 적용
            filtered_results = _apply_filters(search_results, parsed_query)

            # 6. 가격 정렬 적용
            sorted_results = _apply_price_sort(filtered_results, parsed_query.get('price_sort'))

            # 7. 매핑 업데이트
            updated_count = _update_mappings(detected_obj, sorted_results)

            # 8. 진행률 업데이트
            _update_progress(redis_service, refine_id)

            logger.info(f"Refine object {detected_object_id} completed: {updated_count} mappings created")
            span.set("mappings.created", updated_count)
            span.set("status", "SUCCESS")

            return {
                'detected_object_id': detected_object_id,
                'status': 'SUCCESS',
                'mappings_created': updated_count,
            }

        except DetectedObject.DoesNotExist:
            logger.error(f"DetectedObject {detected_object_id} not found")
            span.set("error", "Object not found")
            return {
                'detected_object_id': detected_object_id,
                'status': 'FAILED',
                'error': 'Object not found',
            }
        except Exception as e:
            logger.error(f"Failed to refine object {detected_object_id}: {e}")
            span.set("error", str(e))
            raise self.retry(exc=e)


@shared_task
def refine_analysis_complete(
    results: list[dict],
    refine_id: str,
    analysis_id: int,
):
    """
    모든 객체 재검색이 완료된 후 호출되는 콜백 태스크.
    """
    with create_span(TRACER_NAME, "refine_analysis_complete") as span:
        span.set("refine.id", refine_id)
        span.set("analysis.id", analysis_id)
        span.set("results.count", len(results))

        redis_service = get_redis_service()

        try:
            # 결과 집계
            success_count = sum(1 for r in results if r.get('status') == 'SUCCESS')
            failed_count = sum(1 for r in results if r.get('status') == 'FAILED')
            total_mappings = sum(r.get('mappings_created', 0) for r in results)
            span.set("success.count", success_count)
            span.set("failed.count", failed_count)
            span.set("mappings.total", total_mappings)

            # 최종 상태 업데이트
            redis_service.set(f"refine:{refine_id}:status", "DONE", ttl=RedisService.TTL_REFINE)
            redis_service.set(f"refine:{refine_id}:success_count", str(success_count), ttl=RedisService.TTL_REFINE)
            redis_service.set(f"refine:{refine_id}:failed_count", str(failed_count), ttl=RedisService.TTL_REFINE)
            redis_service.set(f"refine:{refine_id}:total_mappings", str(total_mappings), ttl=RedisService.TTL_REFINE)

            logger.info(
                f"Refine analysis {refine_id} completed: "
                f"{success_count} success, {failed_count} failed, {total_mappings} mappings"
            )

            span.set("status", "DONE")
            return {
                'refine_id': refine_id,
                'analysis_id': analysis_id,
                'status': 'DONE',
                'success_count': success_count,
                'failed_count': failed_count,
                'total_mappings': total_mappings,
            }

        except Exception as e:
            logger.error(f"Failed to complete refine analysis {refine_id}: {e}")
            redis_service.set(f"refine:{refine_id}:status", "FAILED", ttl=RedisService.TTL_REFINE)
            redis_service.set(f"refine:{refine_id}:error", str(e), ttl=RedisService.TTL_REFINE)
            span.set("error", str(e))
            return {
                'refine_id': refine_id,
                'status': 'FAILED',
                'error': str(e),
            }


# =============================================================================
# Helper Functions - 임베딩 생성
# =============================================================================

def _generate_image_embedding(detected_obj) -> Optional[list]:
    """크롭된 이미지에서 임베딩 생성."""
    with create_span(TRACER_NAME, "1_generate_image_embedding") as span:
        span.set("object.id", detected_obj.id)
        embedding_service = get_embedding_service()

        try:
            uploaded_image = detected_obj.uploaded_image
            if not (hasattr(uploaded_image, 'uploaded_image_url') and uploaded_image.uploaded_image_url):
                logger.warning(f"No image URL for object {detected_obj.id}")
                return None

            image_url = uploaded_image.uploaded_image_url

            # bbox 좌표 확인
            has_bbox = (
                detected_obj.bbox_x1 > 0 or detected_obj.bbox_y1 > 0 or
                detected_obj.bbox_x2 > 0 or detected_obj.bbox_y2 > 0
            )

            if not has_bbox:
                logger.warning(f"No bbox for object {detected_obj.id}")
                return None

            # 이미지 다운로드 및 크롭
            cropped_img = _download_and_crop_image(
                image_url,
                detected_obj.bbox_x1,
                detected_obj.bbox_y1,
                detected_obj.bbox_x2,
                detected_obj.bbox_y2,
            )

            # PIL Image를 bytes로 변환
            img_byte_arr = BytesIO()
            cropped_img.save(img_byte_arr, format='JPEG')
            img_bytes = img_byte_arr.getvalue()

            embedding = embedding_service.get_image_embedding(img_bytes)
            logger.info(f"Generated image embedding for object {detected_obj.id}")
            span.set("embedding.generated", True)
            return embedding

        except Exception as e:
            logger.warning(f"Failed to generate image embedding: {e}")
            span.set("error", str(e))
            return None


def _generate_text_embedding(parsed_query: dict, category: str) -> Optional[list]:
    """쿼리에서 텍스트 임베딩 생성."""
    with create_span(TRACER_NAME, "2_generate_text_embedding") as span:
        embedding_service = get_embedding_service()

        # 속성 변경 여부 확인
        if not _has_attribute_change(parsed_query):
            span.set("skipped", "no_attribute_change")
            return None

        # FashionCLIP용 상세 설명 생성 (utils.py 함수 사용)
        search_text = build_fashion_description(parsed_query, category)
        span.set("search_text", search_text[:100])

        embedding = embedding_service.get_text_embedding(search_text)
        logger.info(f"Generated detailed text embedding: '{search_text}'")
        return embedding


def _has_attribute_change(parsed_query: dict) -> bool:
    """속성 변경 요청이 있는지 확인."""
    attribute_keys = [
        'search_keywords', 'style_keywords', 'color_filter',
        'pattern_filter', 'style_vibe', 'sleeve_length',
        'pants_length', 'outer_length', 'material_filter'
    ]
    return any(parsed_query.get(key) for key in attribute_keys)


def _combine_embeddings(
    image_embedding: Optional[list],
    text_embedding: Optional[list],
    parsed_query: dict,
) -> list:
    """이미지/텍스트 임베딩 결합."""
    has_change = _has_attribute_change(parsed_query)

    if has_change and text_embedding is not None:
        if image_embedding is not None:
            # 속성 변경: 이미지 50% + 텍스트 50%
            image_arr = np.array(image_embedding)
            text_arr = np.array(text_embedding)
            combined = 0.5 * image_arr + 0.5 * text_arr
            combined = combined / np.linalg.norm(combined)
            logger.info("Attribute change: image 50% + text 50%")
            return combined.tolist()
        else:
            logger.info("Attribute change: text only (no image)")
            return text_embedding

    elif image_embedding is not None:
        logger.info("Simple research: image only")
        return image_embedding

    elif text_embedding is not None:
        logger.info("Fallback: text only")
        return text_embedding

    else:
        # 폴백: 카테고리 텍스트 임베딩
        embedding_service = get_embedding_service()
        category = parsed_query.get('target_categories', ['unknown'])[0]
        logger.info("Fallback: category text embedding")
        return embedding_service.get_text_embedding(category)


# =============================================================================
# Helper Functions - 검색 및 필터링
# =============================================================================

def _execute_search(embedding: list, category: str) -> list:
    """OpenSearch 검색 실행."""
    with create_span(TRACER_NAME, "3_search_opensearch") as span:
        span.set("service", "opensearch")
        opensearch_service = OpenSearchService()
        search_category = normalize_category(category)
        span.set("category", search_category)

        search_results = opensearch_service.search_similar_products_hybrid(
            embedding=embedding,
            category=search_category,
            k=SearchConfig.REFINE_SEARCH_K,
            search_k=SearchConfig.REFINE_CANDIDATES,
        )

        result_count = len(search_results) if search_results else 0
        span.set("results.count", result_count)
        logger.info(f"Vector search returned {result_count} candidates")
        return search_results or []


def _apply_filters(search_results: list, parsed_query: dict) -> list:
    """속성 필터 적용."""
    with create_span(TRACER_NAME, "4_apply_filters") as span:
        if not search_results:
            span.set("skipped", "no_results")
            return []

        # 필터 조건 확인
        filter_keys = [
            'color_filter', 'brand_filter', 'pattern_filter',
            'style_vibe', 'sleeve_length', 'pants_length',
            'outer_length', 'material_filter'
        ]
        has_filters = any(parsed_query.get(key) for key in filter_keys)
        span.set("has_filters", has_filters)

        if not has_filters:
            return search_results[:SearchConfig.FINAL_RESULTS]

        # 공통 유틸리티로 필터링 (utils.py)
        filtered = apply_attribute_filters(search_results, parsed_query)
        span.set("filtered.count", len(filtered))
        logger.info(f"After attribute filtering: {len(filtered)} results")

        return filtered[:SearchConfig.FINAL_RESULTS]


def _apply_price_sort(results: list, price_sort: Optional[str]) -> list:
    """가격 정렬 적용."""
    if not price_sort or not results:
        return results

    reverse = (price_sort == 'highest')
    return sorted(
        results,
        key=lambda x: int(x.get('price', 0) or 0),
        reverse=reverse
    )


# =============================================================================
# Helper Functions - 매핑 업데이트
# =============================================================================

def _update_mappings(detected_obj, search_results: list) -> int:
    """기존 매핑 삭제 후 새 매핑 생성."""
    with create_span(TRACER_NAME, "5_update_mappings") as span:
        span.set("service", "mysql")
        from analyses.models import ObjectProductMapping

        if not search_results:
            span.set("skipped", "no_results")
            return 0

        # 기존 매핑 soft delete
        deleted = ObjectProductMapping.objects.filter(
            detected_object=detected_obj,
            is_deleted=False
        ).update(is_deleted=True)
        span.set("deleted.count", deleted)

        # 새 매핑 생성
        updated_count = 0
        for result in search_results:
            product_id = result.get('product_id')
            if product_id:
                try:
                    # 공통 유틸리티로 Product 조회/생성
                    product = get_or_create_product_from_search(
                        product_id=str(product_id),
                        search_result=result,
                        default_category=detected_obj.object_category,
                    )

                    ObjectProductMapping.objects.create(
                        detected_object=detected_obj,
                        product=product,
                        confidence_score=result.get('score', 0.0),
                    )
                    updated_count += 1

                except Exception as e:
                    logger.warning(f"Error creating mapping for product {product_id}: {e}")

        span.set("created.count", updated_count)
        return updated_count


def _update_progress(redis_service, refine_id: str):
    """진행률 업데이트."""
    current = redis_service.get(f"refine:{refine_id}:completed") or "0"
    redis_service.set(f"refine:{refine_id}:completed", str(int(current) + 1), ttl=RedisService.TTL_REFINE)


# =============================================================================
# Helper Functions - 유틸리티
# =============================================================================

def _get_default_parsed_query(available_categories: list[str]) -> dict:
    """파싱 실패 시 기본값 반환."""
    return {
        'action': 'research',
        'target_categories': available_categories,
        'search_keywords': None,
        'brand_filter': None,
        'price_filter': None,
        'style_keywords': [],
    }


def _download_and_crop_image(
    image_url: str,
    bbox_x1: float,
    bbox_y1: float,
    bbox_x2: float,
    bbox_y2: float,
) -> Image.Image:
    """
    이미지 URL에서 다운로드 후 바운딩 박스로 크롭.

    storage.py의 download_image를 활용하여 GCS, HTTP, 로컬 파일을 지원합니다.
    """
    # 공통 다운로드 함수 사용
    image_bytes = download_image(image_url)

    img = Image.open(BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # 바운딩 박스 좌표 변환 (normalized → pixels)
    w, h = img.size
    left = int(bbox_x1 * w)
    top = int(bbox_y1 * h)
    right = int(bbox_x2 * w)
    bottom = int(bbox_y2 * h)

    # 여유 마진 추가 (10%)
    margin_x = int((right - left) * 0.1)
    margin_y = int((bottom - top) * 0.1)

    left = max(0, left - margin_x)
    top = max(0, top - margin_y)
    right = min(w, right + margin_x)
    bottom = min(h, bottom + margin_y)

    return img.crop((left, top, right, bottom))
