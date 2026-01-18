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

from services.redis_service import get_redis_service
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
):
    """
    LangChain을 사용하여 자연어 쿼리를 파싱하는 Celery 태스크.

    외부 API 호출: OpenAI API (LangChain)

    Args:
        query: 사용자 자연어 쿼리
        available_categories: 가용 카테고리 목록

    Returns:
        파싱된 쿼리 정보 dict
    """
    from services.langchain_service import get_langchain_service

    try:
        langchain_service = get_langchain_service(temperature=0.3)
        parsed_query = langchain_service.parse_refine_query(query, available_categories)

        logger.info(f"LangChain parsed query: {parsed_query}")
        return parsed_query

    except Exception as e:
        logger.error(f"Failed to parse query with LangChain: {e}")
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
    redis_service = get_redis_service()

    try:
        # 상태 업데이트: RUNNING
        redis_service.set(f"refine:{refine_id}:status", "RUNNING", ttl=3600)
        redis_service.set(f"refine:{refine_id}:progress", "0", ttl=3600)
        redis_service.set(f"refine:{refine_id}:total", str(len(target_object_ids)), ttl=3600)

        logger.info(f"Starting refine analysis {refine_id} for {len(target_object_ids)} objects")

        # 각 객체별 서브태스크 생성
        subtasks = [
            refine_single_object.s(
                refine_id=refine_id,
                detected_object_id=obj_id,
                parsed_query=parsed_query,
            )
            for obj_id in target_object_ids
        ]

        # Celery Group으로 병렬 실행
        callback = refine_analysis_complete.s(refine_id=refine_id, analysis_id=analysis_id)
        chord(subtasks)(callback)

        logger.info(f"Refine analysis {refine_id} tasks dispatched")
        return {'refine_id': refine_id, 'status': 'DISPATCHED', 'task_count': len(subtasks)}

    except Exception as e:
        logger.error(f"Refine analysis {refine_id} failed to start: {e}")
        redis_service.set(f"refine:{refine_id}:status", "FAILED", ttl=3600)
        redis_service.set(f"refine:{refine_id}:error", str(e), ttl=3600)
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
    from analyses.models import DetectedObject

    redis_service = get_redis_service()

    try:
        # 1. DetectedObject 조회
        detected_obj = DetectedObject.objects.get(id=detected_object_id, is_deleted=False)

        # 2. 임베딩 생성 (이미지 + 텍스트)
        image_embedding = _generate_image_embedding(detected_obj)
        text_embedding = _generate_text_embedding(parsed_query, detected_obj.object_category)

        # 3. 임베딩 결합
        embedding = _combine_embeddings(image_embedding, text_embedding, parsed_query)

        # 4. 검색 실행
        search_results = _execute_search(embedding, detected_obj.object_category)

        # 5. 속성 필터 적용
        filtered_results = _apply_filters(search_results, parsed_query)

        # 6. 가격 정렬 적용
        sorted_results = _apply_price_sort(filtered_results, parsed_query.get('price_sort'))

        # 7. 매핑 업데이트
        updated_count = _update_mappings(detected_obj, sorted_results)

        # 8. 진행률 업데이트
        _update_progress(redis_service, refine_id)

        logger.info(f"Refine object {detected_object_id} completed: {updated_count} mappings created")

        return {
            'detected_object_id': detected_object_id,
            'status': 'SUCCESS',
            'mappings_created': updated_count,
        }

    except DetectedObject.DoesNotExist:
        logger.error(f"DetectedObject {detected_object_id} not found")
        return {
            'detected_object_id': detected_object_id,
            'status': 'FAILED',
            'error': 'Object not found',
        }
    except Exception as e:
        logger.error(f"Failed to refine object {detected_object_id}: {e}")
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
    redis_service = get_redis_service()

    try:
        # 결과 집계
        success_count = sum(1 for r in results if r.get('status') == 'SUCCESS')
        failed_count = sum(1 for r in results if r.get('status') == 'FAILED')
        total_mappings = sum(r.get('mappings_created', 0) for r in results)

        # 최종 상태 업데이트
        redis_service.set(f"refine:{refine_id}:status", "DONE", ttl=3600)
        redis_service.set(f"refine:{refine_id}:success_count", str(success_count), ttl=3600)
        redis_service.set(f"refine:{refine_id}:failed_count", str(failed_count), ttl=3600)
        redis_service.set(f"refine:{refine_id}:total_mappings", str(total_mappings), ttl=3600)

        logger.info(
            f"Refine analysis {refine_id} completed: "
            f"{success_count} success, {failed_count} failed, {total_mappings} mappings"
        )

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
        redis_service.set(f"refine:{refine_id}:status", "FAILED", ttl=3600)
        redis_service.set(f"refine:{refine_id}:error", str(e), ttl=3600)
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
    embedding_service = get_embedding_service()

    try:
        uploaded_image = detected_obj.uploaded_image
        if not (hasattr(uploaded_image, 'uploaded_image_url') and uploaded_image.uploaded_image_url):
            logger.warning(f"No image URL for object {detected_obj.id}")
            return None

        image_url = uploaded_image.uploaded_image_url.url

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
        return embedding

    except Exception as e:
        logger.warning(f"Failed to generate image embedding: {e}")
        return None


def _generate_text_embedding(parsed_query: dict, category: str) -> Optional[list]:
    """쿼리에서 텍스트 임베딩 생성."""
    embedding_service = get_embedding_service()

    # 속성 변경 여부 확인
    if not _has_attribute_change(parsed_query):
        return None

    # FashionCLIP용 상세 설명 생성 (utils.py 함수 사용)
    search_text = build_fashion_description(parsed_query, category)

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
    opensearch_service = OpenSearchService()
    search_category = normalize_category(category)

    search_results = opensearch_service.search_similar_products_hybrid(
        embedding=embedding,
        category=search_category,
        k=SearchConfig.REFINE_SEARCH_K,
        search_k=SearchConfig.REFINE_CANDIDATES,
    )

    logger.info(f"Vector search returned {len(search_results)} candidates")
    return search_results or []


def _apply_filters(search_results: list, parsed_query: dict) -> list:
    """속성 필터 적용."""
    if not search_results:
        return []

    # 필터 조건 확인
    filter_keys = [
        'color_filter', 'brand_filter', 'pattern_filter',
        'style_vibe', 'sleeve_length', 'pants_length',
        'outer_length', 'material_filter'
    ]
    has_filters = any(parsed_query.get(key) for key in filter_keys)

    if not has_filters:
        return search_results[:SearchConfig.FINAL_RESULTS]

    # 공통 유틸리티로 필터링 (utils.py)
    filtered = apply_attribute_filters(search_results, parsed_query)
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
    from analyses.models import ObjectProductMapping

    if not search_results:
        return 0

    # 기존 매핑 soft delete
    ObjectProductMapping.objects.filter(
        detected_object=detected_obj,
        is_deleted=False
    ).update(is_deleted=True)

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

    return updated_count


def _update_progress(redis_service, refine_id: str):
    """진행률 업데이트."""
    current = redis_service.get(f"refine:{refine_id}:completed") or "0"
    redis_service.set(f"refine:{refine_id}:completed", str(int(current) + 1), ttl=3600)


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
