"""
Image Analysis Tasks - 이미지 분석 파이프라인.

리팩토링:
- 상수 모듈 활용 (constants.py)
- 공통 유틸리티 활용 (utils.py)
- 장문 함수 분리 (_process_detected_item → 6개 헬퍼)
- Product 생성 로직 통합

Pipeline:
1. Receive image analysis request
2. Google Vision API for object detection (bbox)
3. Crop detected items with padding
4. Upload cropped images to GCS
5. Extract attributes with Claude Haiku (병렬 처리)
6. Generate embeddings using FashionCLIP (병렬 처리)
7. Hybrid search in OpenSearch (k-NN + keyword) (병렬 처리)
8. Claude Haiku reranking (병렬 처리)
9. Save results to MySQL
10. Update status in Redis
"""

import base64
import logging
from typing import Optional

from celery import shared_task, chord
from django.conf import settings
from google.cloud import storage

from services.vision_service import get_vision_service, DetectedItem
from services.embedding_service import get_embedding_service
from services.opensearch_client import OpenSearchService
from services.redis_service import get_redis_service, RedisService
from services.metrics import (
    ANALYSIS_TOTAL,
    ANALYSIS_DURATION,
    ANALYSIS_IN_PROGRESS,
    push_metrics,
)

from analyses.constants import SearchConfig
from analyses.utils import normalize_category, create_span

# Import from refactored task modules to avoid duplication
from analyses.tasks.storage import (
    download_image as _download_image_from_storage,
    upload_cropped_image,
    upload_cropped_image_with_span,
)
from analyses.tasks.image_processing import (
    crop_image as _crop_image_from_processing,
    normalize_result_bbox as _normalize_result_bbox_from_processing,
)
from analyses.tasks.db_operations import (
    update_analysis_status_db as _update_analysis_status_db_from_db_ops,
    save_analysis_results as _save_analysis_results_from_db_ops,
    update_metrics_on_success,
)


logger = logging.getLogger(__name__)

# 트레이서 모듈명
TRACER_NAME = "analyses.tasks.analysis"


# =============================================================================
# Main Celery Tasks
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_image_analysis(
    self,
    analysis_id: str,
    image_url: Optional[str] = None,
    user_id: Optional[int] = None,
    image_b64: Optional[str] = None,
):
    """
    이미지 분석 메인 태스크.

    Vision API로 객체 검출 후, Celery Group을 사용하여
    각 객체를 병렬로 처리합니다 (임베딩 생성 + 검색 + 리랭킹).

    Args:
        analysis_id: Analysis job ID
        image_url: GCS URL of the uploaded image
        user_id: Optional user ID
        image_b64: Optional Base64 encoded image (GCS 다운로드 생략용)

    Returns:
        Analysis result dict
    """
    with create_span(TRACER_NAME, "process_image_analysis") as ctx:
        ctx.set("analysis.id", analysis_id)
        ctx.set("image.url", image_url[:100] if image_url else "none")
        ctx.set("image.direct_bytes", image_b64 is not None)

        # image_url 또는 image_b64 중 하나는 필수
        if not image_url and not image_b64:
            raise ValueError("Either image_url or image_b64 must be provided")

        redis_service = get_redis_service()
        ANALYSIS_IN_PROGRESS.inc()

        try:
            # Update status to RUNNING
            redis_service.update_analysis_running(analysis_id, progress=0)
            logger.info(f"Starting analysis {analysis_id}")

            # Step 1: Get image bytes (직접 전달받았으면 다운로드 생략)
            if image_b64:
                with create_span(TRACER_NAME, "1_decode_image_bytes") as span:
                    span.set("source", "direct_bytes")
                    redis_service.set_analysis_progress(analysis_id, 10)
                    image_bytes = base64.b64decode(image_b64)
                    span.set("image.size_bytes", len(image_bytes))
                    logger.info(f"Using direct image bytes ({len(image_bytes)} bytes)")

                # Step 1.5: Upload original image to GCS and update UploadedImage URL
                with create_span(TRACER_NAME, "1.5_upload_original_to_gcs") as span:
                    span.set("service", "google_cloud_storage")
                    try:
                        from analyses.models import ImageAnalysis
                        from google.cloud import storage
                        import uuid

                        analysis = ImageAnalysis.objects.select_related('uploaded_image').get(id=analysis_id)
                        uploaded_image = analysis.uploaded_image

                        # GCS에 원본 이미지 업로드
                        if uploaded_image and not uploaded_image.uploaded_image_url:
                            bucket_name = os.environ.get('GCS_BUCKET_NAME', 'team-g-bucket')
                            unique_filename = f"uploaded-images/{analysis_id}/{uuid.uuid4().hex}.jpg"

                            client = storage.Client()
                            bucket = client.bucket(bucket_name)
                            blob = bucket.blob(unique_filename)
                            blob.upload_from_string(image_bytes, content_type='image/jpeg')

                            # Public URL 생성
                            gcs_url = f"https://storage.googleapis.com/{bucket_name}/{unique_filename}"
                            uploaded_image.uploaded_image_url = gcs_url
                            uploaded_image.save(update_fields=['uploaded_image_url'])

                            span.set("uploaded_image.url", gcs_url[:100])
                            logger.info(f"Uploaded original image to GCS: {gcs_url}")
                    except Exception as e:
                        logger.warning(f"Failed to upload original image to GCS: {e}")
                        span.set("upload_error", str(e))
            else:
                with create_span(TRACER_NAME, "1_download_image_gcs") as span:
                    span.set("service", "google_cloud_storage")
                    redis_service.set_analysis_progress(analysis_id, 10)
                    with ANALYSIS_DURATION.labels(stage='download_image').time():
                        image_bytes = _download_image(image_url)
                    span.set("image.size_bytes", len(image_bytes))

            # Step 2: Detect objects with Vision API
            with create_span(TRACER_NAME, "2_detect_objects_vision_api") as span:
                span.set("service", "google_vision_api")
                redis_service.set_analysis_progress(analysis_id, 20)
                with ANALYSIS_DURATION.labels(stage='detect_objects').time():
                    vision_service = get_vision_service()
                    detected_items = vision_service.detect_objects_from_bytes(image_bytes)
                span.set("detected.count", len(detected_items))
                if detected_items:
                    span.set("detected.categories", ",".join(set(i.category for i in detected_items)))

            logger.info(f"Detected {len(detected_items)} items")

            if not detected_items:
                redis_service.update_analysis_done(analysis_id, {'items': []})
                _update_analysis_status_db(analysis_id, 'DONE')
                ctx.set("result", "no_items_detected")
                return {'analysis_id': analysis_id, 'items': []}

            # Step 3: Encode image for parallel processing
            with create_span(TRACER_NAME, "3_encode_image_base64"):
                image_b64 = base64.b64encode(image_bytes).decode('utf-8')

            # Step 4: Create subtasks for parallel processing
            with create_span(TRACER_NAME, "4_dispatch_parallel_tasks") as span:
                subtasks = []
                for idx, item in enumerate(detected_items):
                    subtasks.append(
                        process_single_item.s(
                            analysis_id=analysis_id,
                            image_b64=image_b64,
                            detected_item_dict={
                                'category': item.category,
                                'bbox': {
                                    'x_min': item.bbox.x_min,
                                    'y_min': item.bbox.y_min,
                                    'x_max': item.bbox.x_max,
                                    'y_max': item.bbox.y_max,
                                },
                                'confidence': item.confidence,
                            },
                            item_index=idx,
                        )
                    )

                callback = analysis_complete_callback.s(
                    analysis_id=analysis_id,
                    user_id=user_id,
                    total_items=len(detected_items),
                )

                chord(subtasks)(callback)
                span.set("tasks.count", len(subtasks))

            logger.info(f"Analysis {analysis_id}: dispatched {len(subtasks)} parallel tasks")
            ctx.set("status", "PROCESSING")
            ctx.set("parallel_tasks", len(subtasks))

            return {'analysis_id': analysis_id, 'status': 'PROCESSING', 'task_count': len(subtasks)}

        except Exception as e:
            logger.error(f"Analysis {analysis_id} failed: {e}")
            redis_service.update_analysis_failed(analysis_id, str(e))
            _update_analysis_status_db(analysis_id, 'FAILED')
            ctx.set("error", str(e))
            raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def process_single_item(
    self,
    analysis_id: str,
    image_b64: str,
    detected_item_dict: dict,
    item_index: int,
):
    """
    단일 검출 객체 처리 태스크 (병렬 실행됨).

    Args:
        analysis_id: Analysis job ID
        image_b64: Base64 encoded image
        detected_item_dict: Detected item as dict
        item_index: Item index

    Returns:
        Processed item result
    """
    with create_span(TRACER_NAME, f"process_single_item_{item_index}") as ctx:
        ctx.set("analysis.id", analysis_id)
        ctx.set("item.index", item_index)
        ctx.set("item.category", detected_item_dict.get('category', 'unknown'))

        redis_service = get_redis_service()

        try:
            # Base64 디코딩
            image_bytes = base64.b64decode(image_b64)

            # DetectedItem 복원
            detected_item = DetectedItem(
                category=detected_item_dict['category'],
                bbox=type('BBox', (), detected_item_dict['bbox'])(),
                confidence=detected_item_dict['confidence'],
            )

            # 객체 처리 파이프라인 실행
            result = _process_detected_item(
                analysis_id=analysis_id,
                image_bytes=image_bytes,
                detected_item=detected_item,
                item_index=item_index,
            )

            # 진행률 업데이트
            completed_key = f"analysis:{analysis_id}:completed"
            current = redis_service.get(completed_key) or "0"
            redis_service.set(completed_key, str(int(current) + 1), ttl=RedisService.TTL_POLLING)

            logger.info(f"Analysis {analysis_id} item {item_index} processed")
            ctx.set("result.matches", len(result.get('matches', [])) if result else 0)

            return result

        except Exception as e:
            logger.error(f"Failed to process item {item_index} for analysis {analysis_id}: {e}")
            ctx.set("error", str(e))
            raise self.retry(exc=e)


@shared_task
def analysis_complete_callback(
    results: list[dict],
    analysis_id: str,
    user_id: Optional[int],
    total_items: int,
):
    """
    모든 객체 처리 완료 후 호출되는 콜백 태스크.
    결과를 DB에 저장하고 상태를 업데이트합니다.
    """
    with create_span(TRACER_NAME, "analysis_complete_callback") as ctx:
        ctx.set("analysis.id", analysis_id)
        ctx.set("total_items", total_items)

        redis_service = get_redis_service()

        try:
            # None 결과 필터링
            valid_results = [r for r in results if r is not None]
            ctx.set("valid_results", len(valid_results))

            # DB에 결과 저장
            with create_span(TRACER_NAME, "7_save_results_to_db") as span:
                span.set("service", "mysql")
                span.set("records_count", len(valid_results))
                redis_service.set_analysis_progress(analysis_id, 90)
                with ANALYSIS_DURATION.labels(stage='save_results').time():
                    _save_analysis_results(analysis_id, valid_results, user_id)

            # 완료 상태 업데이트
            with create_span(TRACER_NAME, "8_update_status"):
                redis_service.update_analysis_done(analysis_id, {'items': valid_results})
                _update_analysis_status_db(analysis_id, 'DONE')

            # Metrics 업데이트
            _update_metrics(valid_results)
            ANALYSIS_IN_PROGRESS.dec()

            logger.info(f"Analysis {analysis_id} completed: {len(valid_results)}/{total_items} items processed")
            ctx.set("status", "DONE")

            push_metrics()

            # 스타일 태그 추출 태스크 비동기 호출 (실패해도 분석에 영향 없음)
            try:
                extract_style_tags_task.delay(analysis_id)
            except Exception as e:
                logger.warning(f"Failed to trigger style tag extraction: {e}")

            return {
                'analysis_id': analysis_id,
                'status': 'DONE',
                'processed_items': len(valid_results),
                'total_items': total_items,
            }

        except Exception as e:
            logger.error(f"Failed to complete analysis {analysis_id}: {e}")
            redis_service.update_analysis_failed(analysis_id, str(e))
            _update_analysis_status_db(analysis_id, 'FAILED')
            ctx.set("status", "FAILED")
            ctx.set("error", str(e))

            ANALYSIS_TOTAL.labels(status='failed').inc()
            ANALYSIS_IN_PROGRESS.dec()
            push_metrics()

            return {'analysis_id': analysis_id, 'status': 'FAILED', 'error': str(e)}


@shared_task
def process_detected_item_task(
    analysis_id: str,
    image_bytes: bytes,
    detected_item_dict: dict,
    item_index: int,
):
    """Legacy task wrapper for backward compatibility."""
    detected_item = DetectedItem(
        category=detected_item_dict['category'],
        bbox=detected_item_dict['bbox'],
        confidence=detected_item_dict['confidence'],
    )

    return _process_detected_item(
        analysis_id=analysis_id,
        image_bytes=image_bytes,
        detected_item=detected_item,
        item_index=item_index,
    )


# =============================================================================
# Helper Functions - 객체 처리 파이프라인
# =============================================================================

def _process_detected_item(
    analysis_id: str,
    image_bytes: bytes,
    detected_item: DetectedItem,
    item_index: int,
) -> Optional[dict]:
    """
    단일 검출 객체 처리 파이프라인.

    병렬 실행으로 최적화:
    - GCS 업로드: 백그라운드 실행
    - Claude 속성추출 + 임베딩 생성: 병렬 실행
    """
    from concurrent.futures import ThreadPoolExecutor
    from opentelemetry import context as otel_context

    try:
        # 1. 이미지 크롭 (동기)
        with create_span(TRACER_NAME, "1_crop_image") as span:
            span.set("item.index", item_index)
            span.set("item.category", detected_item.category)
            cropped_bytes, pixel_bbox = _crop_image(image_bytes, detected_item)

        # 현재 트레이스 컨텍스트 캡처 (스레드 전파용)
        current_context = otel_context.get_current()

        def run_with_context(func, *args, **kwargs):
            """트레이스 컨텍스트를 유지하며 함수 실행."""
            token = otel_context.attach(current_context)
            try:
                return func(*args, **kwargs)
            finally:
                otel_context.detach(token)

        # 2. 병렬 실행: GCS 업로드 + Claude 속성추출 + 임베딩 생성
        with ThreadPoolExecutor(max_workers=3) as executor:
            # GCS 업로드 (백그라운드)
            gcs_future = executor.submit(
                run_with_context,
                _upload_to_gcs_with_span,
                image_bytes=cropped_bytes,
                analysis_id=analysis_id,
                item_index=item_index,
                category=detected_item.category,
            )

            # Claude 속성추출
            attr_future = executor.submit(
                run_with_context,
                _extract_attributes, cropped_bytes, detected_item.category
            )

            # 임베딩 생성
            embed_future = executor.submit(
                run_with_context,
                _generate_embedding, cropped_bytes
            )

            # 임베딩과 속성 완료 대기 (GCS는 기다리지 않음)
            attributes = attr_future.result()
            embedding = embed_future.result()

        # 3. 검색 (임베딩 + 속성 필요)
        search_results = _search_opensearch(
            embedding, detected_item.category, attributes
        )

        if not search_results:
            logger.warning(f"No matching products found for item {item_index}")
            return None

        # 4. 리랭킹 (Claude)
        ranked_results = _rerank_results(cropped_bytes, search_results)

        # 5. GCS URL 가져오기 (이 시점에는 이미 완료됨)
        cropped_image_url = gcs_future.result()

        # 6. 결과 포맷팅
        return _format_item_result(
            item_index, detected_item, pixel_bbox,
            cropped_image_url, ranked_results, attributes
        )

    except Exception as e:
        logger.error(f"Failed to process item {item_index}: {e}")
        return None


def _upload_to_gcs_with_span(
    image_bytes: bytes,
    analysis_id: str,
    item_index: int,
    category: str,
) -> Optional[str]:
    """GCS 업로드 (트레이싱 포함, 병렬 실행용)."""
    with create_span(TRACER_NAME, "2_upload_to_gcs") as span:
        span.set("service", "google_cloud_storage")
        return _upload_to_gcs(
            image_bytes=image_bytes,
            analysis_id=analysis_id,
            item_index=item_index,
            category=category,
        )


def _extract_attributes(cropped_bytes: bytes, category: str) -> Optional[object]:
    """Claude Vision으로 속성 추출."""
    from services.gpt4v_service import get_gpt4v_service

    with create_span(TRACER_NAME, "3_extract_attributes_claude") as span:
        span.set("service", "anthropic_claude")
        span.set("purpose", "color_brand_style_extraction")
        try:
            gpt4v_service = get_gpt4v_service()
            with ANALYSIS_DURATION.labels(stage='extract_attributes').time():
                attributes = gpt4v_service.extract_attributes(
                    image_bytes=cropped_bytes,
                    category=category,
                )
            span.set("extracted.color", attributes.color or "unknown")
            span.set("extracted.brand", attributes.brand or "unknown")
            logger.info(f"GPT-4V attributes: color={attributes.color}, brand={attributes.brand}")
            return attributes
        except Exception as e:
            span.set("error", str(e))
            logger.warning(f"GPT-4V extraction failed: {e}")
            return None


def _generate_embedding(cropped_bytes: bytes) -> list[float]:
    """FashionCLIP 임베딩 생성 (병렬 실행용)."""
    with create_span(TRACER_NAME, "3_generate_embedding_fashionclip") as span:
        span.set("service", "marqo_fashionclip")
        span.set("embedding_dim", 512)
        embedding_service = get_embedding_service()
        with ANALYSIS_DURATION.labels(stage='generate_embedding').time():
            embedding = embedding_service.get_image_embedding(cropped_bytes)
        return embedding


def _search_opensearch(
    embedding: list[float],
    category: str,
    attributes: Optional[object],
) -> list[dict]:
    """OpenSearch k-NN 검색."""
    # 카테고리 정규화 및 속성 추출
    search_category = normalize_category(category)
    detected_brand = attributes.brand if attributes else None
    detected_color = attributes.color if attributes else None
    detected_secondary = attributes.secondary_color if attributes else None
    detected_item_type = attributes.item_type if attributes else None

    # OpenSearch 검색
    with create_span(TRACER_NAME, "4_search_opensearch_knn") as span:
        span.set("service", "opensearch")
        span.set("search.category", search_category)
        span.set("search.brand", detected_brand or "none")
        span.set("search.color", detected_color or "none")
        span.set("search.k", SearchConfig.K)

        opensearch_service = OpenSearchService()
        logger.info(f"Vector search → brand/color boost (brand={detected_brand}, color={detected_color})")

        with ANALYSIS_DURATION.labels(stage='search_products').time():
            search_results = opensearch_service.search_vector_then_filter(
                embedding=embedding,
                category=search_category,
                brand=detected_brand,
                color=detected_color,
                secondary_color=detected_secondary,
                item_type=detected_item_type,
                k=SearchConfig.K,
                search_k=SearchConfig.SEARCH_K,
            )

        span.set("results.count", len(search_results) if search_results else 0)

    return search_results or []


def _rerank_results(cropped_bytes: bytes, search_results: list[dict]) -> list[dict]:
    """Claude로 리랭킹."""
    from services.gpt4v_service import get_gpt4v_service

    with create_span(TRACER_NAME, "5_rerank_claude") as span:
        span.set("service", "anthropic_claude")
        span.set("purpose", "visual_reranking")
        span.set("candidates_count", min(SearchConfig.RERANK_TOP_K, len(search_results)))

        try:
            gpt4v_service = get_gpt4v_service()
            with ANALYSIS_DURATION.labels(stage='rerank_products').time():
                ranked = gpt4v_service.rerank_products(
                    query_image_bytes=cropped_bytes,
                    candidates=search_results[:SearchConfig.RERANK_TOP_K],
                    top_k=SearchConfig.FINAL_RESULTS,
                )
            logger.info("Claude reranking completed")
            return ranked
        except Exception as e:
            span.set("error", str(e))
            span.set("fallback", "using_original_order")
            logger.warning(f"Claude reranking failed, using original results: {e}")
            return search_results[:SearchConfig.FINAL_RESULTS]


def _format_item_result(
    item_index: int,
    detected_item: DetectedItem,
    pixel_bbox: dict,
    cropped_image_url: Optional[str],
    search_results: list[dict],
    attributes: Optional[object],
) -> dict:
    """검출 결과 포맷팅."""
    # 상위 매칭 결과 정리
    top_matches = []
    for match in search_results[:SearchConfig.FINAL_RESULTS]:
        top_matches.append({
            'product_id': match['product_id'],
            'score': match.get('combined_score', match['score']),
            'name': match.get('name'),
            'image_url': match.get('image_url'),
            'price': match.get('price'),
        })

    result = {
        'index': item_index,
        'category': detected_item.category,
        'bbox': pixel_bbox,
        'confidence': detected_item.confidence,
        'cropped_image_url': cropped_image_url,
        'matches': top_matches,
    }

    # 속성 정보 추가
    if attributes:
        result['attributes'] = {
            'color': attributes.color,
            'secondary_color': attributes.secondary_color,
            'brand': attributes.brand,
            'material': attributes.material,
            'style': attributes.style,
            'pattern': attributes.pattern,
        }

    return result


# =============================================================================
# Helper Functions - 공통 유틸리티 (다른 모듈로 위임)
# =============================================================================

def _update_analysis_status_db(analysis_id: str, status: str):
    """DB의 ImageAnalysis 상태 업데이트. (db_operations 모듈로 위임)"""
    _update_analysis_status_db_from_db_ops(analysis_id, status)


def _update_metrics(valid_results: list[dict]):
    """분석 완료 메트릭 업데이트. (db_operations 모듈로 위임)"""
    update_metrics_on_success(valid_results)


def _download_image(image_url: str) -> bytes:
    """Download image from URL or local file path. (storage 모듈로 위임)"""
    return _download_image_from_storage(image_url)


def _upload_to_gcs(
    image_bytes: bytes,
    analysis_id: str,
    item_index: int,
    category: str,
) -> Optional[str]:
    """Upload cropped image to GCS. (storage 모듈로 위임)"""
    return upload_cropped_image(
        image_bytes=image_bytes,
        analysis_id=analysis_id,
        item_index=item_index,
        category=category,
    )


def _crop_image(
    image_bytes: bytes,
    item: DetectedItem,
    padding_ratio: float = None,
) -> tuple[bytes, dict]:
    """Crop detected item from image with padding. (image_processing 모듈로 위임)"""
    return _crop_image_from_processing(image_bytes, item, padding_ratio)


def _save_analysis_results(
    analysis_id: str,
    results: list[dict],
    user_id: Optional[int],
):
    """Save analysis results to MySQL using bulk operations. (db_operations 모듈로 위임)"""
    _save_analysis_results_from_db_ops(analysis_id, results, user_id)


def _normalize_result_bbox(bbox: dict) -> dict:
    """결과의 bbox를 0-1 범위로 정규화. (image_processing 모듈로 위임)"""
    return _normalize_result_bbox_from_processing(bbox)


# =============================================================================
# Style Tag Extraction Task
# =============================================================================

@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def extract_style_tags_task(self, analysis_id: str):
    """
    코디 이미지에서 스타일 태그 추출.

    분석 완료 후 비동기로 호출되어 UploadedImage에 스타일 태그를 저장합니다.
    실패해도 분석 결과에는 영향 없음.
    """
    from analyses.models import ImageAnalysis
    from services.gpt4v_service import get_gpt4v_service

    with create_span(TRACER_NAME, "extract_style_tags") as ctx:
        ctx.set("analysis.id", analysis_id)

        try:
            # 분석 및 원본 이미지 조회
            analysis = ImageAnalysis.objects.select_related('uploaded_image').get(id=analysis_id)
            uploaded_image = analysis.uploaded_image

            if not uploaded_image or not uploaded_image.uploaded_image_url:
                logger.warning(f"No image URL for analysis {analysis_id}")
                return {'status': 'skipped', 'reason': 'no_image_url'}

            # 이미지 다운로드
            image_bytes = _download_image(uploaded_image.uploaded_image_url)

            # Claude Vision으로 스타일 태그 추출
            gpt4v_service = get_gpt4v_service()
            style_tag1, style_tag2 = gpt4v_service.extract_style_tags(image_bytes)

            # UploadedImage에 저장
            uploaded_image.style_tag1 = style_tag1
            uploaded_image.style_tag2 = style_tag2
            uploaded_image.save(update_fields=['style_tag1', 'style_tag2', 'updated_at'])

            logger.info(
                f"Style tags extracted for analysis {analysis_id}",
                extra={
                    'event': 'style_tags_saved',
                    'analysis_id': analysis_id,
                    'style_tag1': style_tag1,
                    'style_tag2': style_tag2,
                }
            )

            ctx.set("style_tag1", style_tag1 or "none")
            ctx.set("style_tag2", style_tag2 or "none")

            return {
                'status': 'success',
                'style_tag1': style_tag1,
                'style_tag2': style_tag2,
            }

        except ImageAnalysis.DoesNotExist:
            logger.error(f"ImageAnalysis {analysis_id} not found for style tag extraction")
            return {'status': 'error', 'reason': 'analysis_not_found'}

        except Exception as e:
            logger.error(f"Style tag extraction failed for {analysis_id}: {e}")
            ctx.set("error", str(e))
            raise self.retry(exc=e)
