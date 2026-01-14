"""
Celery Tasks for Image Analysis Pipeline.

Pipeline:
1. Receive image analysis request
2. Google Vision API for object detection (bbox)
3. Crop detected items with padding
4. Generate embeddings using FashionCLIP (병렬 처리)
5. Hybrid search in OpenSearch (k-NN + keyword) (병렬 처리)
6. BLIP + CLIP re-ranking for better accuracy (병렬 처리)
7. Save results to MySQL
8. Update status in Redis

비동기 처리:
- RabbitMQ: 메시지 브로커로 태스크 큐잉
- Celery Group: 여러 객체를 병렬로 처리
- Redis: 진행 상태 및 결과 캐싱
"""

import io
import logging
from typing import Optional

from celery import shared_task, group, chord
from django.conf import settings
from PIL import Image

from services.vision_service import get_vision_service, DetectedItem
from services.embedding_service import get_embedding_service
from services.opensearch_client import OpenSearchService
from services.redis_service import get_redis_service

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_image_analysis(
    self,
    analysis_id: str,
    image_url: str,
    user_id: Optional[int] = None,
):
    """
    이미지 분석 메인 태스크.

    Vision API로 객체 검출 후, Celery Group을 사용하여
    각 객체를 병렬로 처리합니다 (임베딩 생성 + 검색 + 리랭킹).

    Args:
        analysis_id: Analysis job ID
        image_url: GCS URL of the uploaded image
        user_id: Optional user ID

    Returns:
        Analysis result dict
    """
    import base64
    redis_service = get_redis_service()

    try:
        # Update status to RUNNING
        redis_service.update_analysis_running(analysis_id, progress=0)
        logger.info(f"Starting analysis {analysis_id}")

        # Step 1: Download image from GCS
        redis_service.set_analysis_progress(analysis_id, 10)
        image_bytes = _download_image(image_url)

        # Step 2: Detect objects with Vision API (외부 API 호출)
        redis_service.set_analysis_progress(analysis_id, 20)
        detected_items = _detect_objects(image_bytes)
        logger.info(f"Detected {len(detected_items)} items")

        if not detected_items:
            redis_service.update_analysis_done(analysis_id, {'items': []})
            _update_analysis_status_db(analysis_id, 'DONE')
            return {'analysis_id': analysis_id, 'items': []}

        # Step 3: 병렬 처리를 위해 이미지를 base64로 인코딩
        # (Celery는 bytes를 직접 전달하기 어려움)
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        # Step 4: 각 객체별 서브태스크 생성 (병렬 처리)
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

        # Step 5: Celery chord로 병렬 실행 후 결과 수집
        # chord: 모든 서브태스크 완료 후 콜백 실행
        callback = analysis_complete_callback.s(
            analysis_id=analysis_id,
            user_id=user_id,
            total_items=len(detected_items),
        )

        job = chord(subtasks)(callback)
        logger.info(f"Analysis {analysis_id}: dispatched {len(subtasks)} parallel tasks")

        return {'analysis_id': analysis_id, 'status': 'PROCESSING', 'task_count': len(subtasks)}

    except Exception as e:
        logger.error(f"Analysis {analysis_id} failed: {e}")
        redis_service.update_analysis_failed(analysis_id, str(e))
        _update_analysis_status_db(analysis_id, 'FAILED')
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

    외부 API 호출:
    - FashionCLIP: 이미지 임베딩 생성
    - OpenSearch: k-NN 하이브리드 검색
    - BLIP+CLIP: 리랭킹

    Args:
        analysis_id: Analysis job ID
        image_b64: Base64 encoded image
        detected_item_dict: Detected item as dict
        item_index: Item index

    Returns:
        Processed item result
    """
    import base64
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

        # 객체 처리 (크롭 → 임베딩 → 검색 → 리랭킹)
        result = _process_detected_item(
            analysis_id=analysis_id,
            image_bytes=image_bytes,
            detected_item=detected_item,
            item_index=item_index,
        )

        # 진행률 업데이트
        completed_key = f"analysis:{analysis_id}:completed"
        current = redis_service.get(completed_key) or "0"
        redis_service.set(completed_key, str(int(current) + 1), ttl=3600)

        logger.info(f"Analysis {analysis_id} item {item_index} processed")
        return result

    except Exception as e:
        logger.error(f"Failed to process item {item_index} for analysis {analysis_id}: {e}")
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

    Args:
        results: 각 서브태스크의 결과 목록
        analysis_id: Analysis job ID
        user_id: Optional user ID
        total_items: Total detected items count

    Returns:
        Final analysis result
    """
    redis_service = get_redis_service()

    try:
        # None 결과 필터링
        valid_results = [r for r in results if r is not None]

        # DB에 결과 저장
        redis_service.set_analysis_progress(analysis_id, 90)
        _save_analysis_results(analysis_id, valid_results, user_id)

        # 완료 상태 업데이트
        redis_service.update_analysis_done(analysis_id, {'items': valid_results})
        _update_analysis_status_db(analysis_id, 'DONE')

        logger.info(f"Analysis {analysis_id} completed: {len(valid_results)}/{total_items} items processed")

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
        return {
            'analysis_id': analysis_id,
            'status': 'FAILED',
            'error': str(e),
        }


def _update_analysis_status_db(analysis_id: str, status: str):
    """DB의 ImageAnalysis 상태 업데이트 헬퍼 함수."""
    from analyses.models import ImageAnalysis
    try:
        analysis = ImageAnalysis.objects.get(id=analysis_id)
        analysis.image_analysis_status = status
        analysis.save(update_fields=['image_analysis_status', 'updated_at'])
    except ImageAnalysis.DoesNotExist:
        logger.error(f"ImageAnalysis {analysis_id} not found for status update")


@shared_task
def process_detected_item_task(
    analysis_id: str,
    image_bytes: bytes,
    detected_item_dict: dict,
    item_index: int,
):
    """
    Task for processing a single detected item (for parallel processing).

    Args:
        analysis_id: Analysis job ID
        image_bytes: Original image bytes
        detected_item_dict: Detected item as dict
        item_index: Item index

    Returns:
        Processed item result
    """
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


def _download_image(image_url: str) -> bytes:
    """Download image from URL or local file path."""
    import os
    from google.cloud import storage

    # Convert GCS HTTPS URL to gs:// format
    # https://storage.googleapis.com/bucket/path -> gs://bucket/path
    if 'storage.googleapis.com' in image_url:
        parts = image_url.split('storage.googleapis.com/')
        if len(parts) > 1:
            image_url = 'gs://' + parts[1]

    # Parse GCS URL: gs://bucket/path/to/file
    if image_url.startswith('gs://'):
        parts = image_url[5:].split('/', 1)
        bucket_name = parts[0]
        blob_name = parts[1] if len(parts) > 1 else ''

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        return blob.download_as_bytes()
    elif image_url.startswith('/media/'):
        # Local media file - read directly from filesystem
        local_path = settings.BASE_DIR / image_url.lstrip('/')
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        with open(local_path, 'rb') as f:
            return f.read()
    elif image_url.startswith('http://') or image_url.startswith('https://'):
        # HTTP URL - use requests
        import requests
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        return response.content
    else:
        raise ValueError(f"Unsupported URL format: {image_url}")


def _detect_objects(image_bytes: bytes) -> list[DetectedItem]:
    """Detect fashion items in image."""
    vision_service = get_vision_service()
    return vision_service.detect_objects_from_bytes(image_bytes)


def _process_detected_item(
    analysis_id: str,
    image_bytes: bytes,
    detected_item: DetectedItem,
    item_index: int,
) -> Optional[dict]:
    """
    Process a single detected item.

    1. Crop the item from image
    2. Upload cropped image to GCS
    3. Generate embedding
    4. Search similar products
    5. Evaluate with LangChain

    Args:
        analysis_id: Analysis job ID
        image_bytes: Original image bytes
        detected_item: Detected item
        item_index: Item index

    Returns:
        Processed item result
    """
    try:
        # Step 1: Crop image and get pixel bbox
        cropped_bytes, pixel_bbox = _crop_image(image_bytes, detected_item)

        # Step 2: Generate embedding
        embedding_service = get_embedding_service()
        embedding = embedding_service.get_image_embedding(cropped_bytes)

        # Step 3: Search similar products
        # Vision API 카테고리 → OpenSearch 카테고리 매핑
        category_mapping = {
            'bottom': 'pants',
            'outerwear': 'outer',
        }
        search_category = category_mapping.get(detected_item.category, detected_item.category)

        opensearch_service = OpenSearchService()
        # 1차: 하이브리드 검색으로 후보 30개 가져오기
        search_results = opensearch_service.search_similar_products_hybrid(
            embedding=embedding,
            category=search_category,
            k=30,
            search_k=100,
        )

        if not search_results:
            logger.warning(f"No matching products found for item {item_index}")
            return None

        # 2차: BLIP + CLIP 리랭킹
        from services.blip_service import get_blip_service
        try:
            blip_service = get_blip_service()
            search_results = blip_service.rerank_products(
                image_bytes=cropped_bytes,
                candidates=search_results,
                top_k=5,
                image_embedding=embedding,  # CLIP cross-encoder용
                category=detected_item.category,  # 카테고리별 프롬프트용
            )
            logger.info(f"Item {item_index} - BLIP + CLIP re-ranking completed")
        except Exception as e:
            logger.warning(f"BLIP re-ranking failed, using original results: {e}")
            search_results = search_results[:5]

        # 상위 5개 매칭 결과 반환
        top_matches = []
        for match in search_results[:5]:
            top_matches.append({
                'product_id': match['product_id'],
                'score': match.get('combined_score', match['score']),
                'name': match.get('name'),
                'image_url': match.get('image_url'),
                'price': match.get('price'),
            })

        return {
            'index': item_index,
            'category': detected_item.category,
            'bbox': pixel_bbox,
            'confidence': detected_item.confidence,
            'matches': top_matches,  # 상위 5개
        }

    except Exception as e:
        logger.error(f"Failed to process item {item_index}: {e}")
        return None


def _crop_image(image_bytes: bytes, item: DetectedItem, padding_ratio: float = 0.25) -> tuple[bytes, dict]:
    """
    Crop detected item from image with padding for better embedding quality.

    Args:
        image_bytes: Original image bytes
        item: Detected item with bounding box
        padding_ratio: Padding as ratio of bbox size (default 25%)

    Returns:
        Tuple of (cropped image bytes, pixel bbox dict)
    """
    image = Image.open(io.BytesIO(image_bytes))
    width, height = image.size

    # Convert normalized coordinates (0-1000) to pixels
    bbox = item.bbox
    x_min = int(bbox.x_min * width / 1000)
    y_min = int(bbox.y_min * height / 1000)
    x_max = int(bbox.x_max * width / 1000)
    y_max = int(bbox.y_max * height / 1000)

    # Original pixel bbox for storage (without padding)
    pixel_bbox = {
        'x_min': x_min,
        'y_min': y_min,
        'x_max': x_max,
        'y_max': y_max,
        'width': x_max - x_min,
        'height': y_max - y_min,
    }

    # Add padding for better embedding (more context helps CLIP)
    bbox_width = x_max - x_min
    bbox_height = y_max - y_min
    pad_x = int(bbox_width * padding_ratio)
    pad_y = int(bbox_height * padding_ratio)

    # Expanded bbox with padding (clamped to image bounds)
    crop_x_min = max(0, x_min - pad_x)
    crop_y_min = max(0, y_min - pad_y)
    crop_x_max = min(width, x_max + pad_x)
    crop_y_max = min(height, y_max + pad_y)

    # Crop with padding
    cropped = image.crop((crop_x_min, crop_y_min, crop_x_max, crop_y_max))

    # Convert to bytes
    output = io.BytesIO()
    cropped.save(output, format='JPEG', quality=95)
    return output.getvalue(), pixel_bbox


def _save_analysis_results(
    analysis_id: str,
    results: list[dict],
    user_id: Optional[int],
):
    """
    Save analysis results to MySQL.

    Updates:
    - ImageAnalysis: status = DONE
    - DetectedObject: insert detected items with bbox
    - ObjectProductMapping: insert top matches for each object
    """
    from analyses.models import ImageAnalysis, DetectedObject, ObjectProductMapping
    from products.models import Product

    try:
        # 1. ImageAnalysis 조회 및 상태 업데이트
        analysis = ImageAnalysis.objects.select_related('uploaded_image').get(id=analysis_id)
        uploaded_image = analysis.uploaded_image

        # 이미지 크기 가져오기 (정규화용)
        try:
            img = Image.open(uploaded_image.uploaded_image_url.path)
            img_width, img_height = img.size
        except Exception as e:
            logger.warning(f"Could not get image size: {e}, using default 1000x1000")
            img_width, img_height = 1000, 1000

        # 2. 각 검출 결과에 대해 DetectedObject 및 매핑 생성
        for result in results:
            # bbox를 0-1 범위로 정규화
            bbox = result.get('bbox', {})
            normalized_bbox = {
                'x1': bbox.get('x_min', 0) / img_width,
                'y1': bbox.get('y_min', 0) / img_height,
                'x2': bbox.get('x_max', 0) / img_width,
                'y2': bbox.get('y_max', 0) / img_height,
            }

            # DetectedObject 생성
            detected_object = DetectedObject.objects.create(
                uploaded_image=uploaded_image,
                object_category=result.get('category', 'unknown'),
                bbox_x1=normalized_bbox['x1'],
                bbox_y1=normalized_bbox['y1'],
                bbox_x2=normalized_bbox['x2'],
                bbox_y2=normalized_bbox['y2'],
            )

            logger.info(f"Created DetectedObject {detected_object.id} - {result.get('category')}")

            # ObjectProductMapping 생성 (상위 매칭 상품들 - Product 자동 생성 포함)
            matches = result.get('matches', [])
            mapping_count = 0
            for match in matches:
                product_id = match.get('product_id')  # 무신사 itemId
                if product_id:
                    try:
                        # 1. 기존 Product 검색
                        product = Product.objects.filter(
                            product_url__endswith=f'/{product_id}'
                        ).first()

                        # 2. 없으면 검색 결과로 자동 생성
                        if not product:
                            product, created = Product.objects.update_or_create(
                                product_url=f'https://www.musinsa.com/app/goods/{product_id}',
                                defaults={
                                    'brand_name': match.get('brand', 'Unknown') or 'Unknown',
                                    'product_name': match.get('name', 'Unknown') or 'Unknown',
                                    'category': result.get('category', 'unknown'),
                                    'selling_price': int(match.get('price', 0) or 0),
                                    'product_image_url': match.get('image_url', '') or '',
                                }
                            )
                            if created:
                                logger.info(f"Auto-created Product {product_id}")

                        # 3. 매핑 생성
                        ObjectProductMapping.objects.create(
                            detected_object=detected_object,
                            product=product,
                            confidence_score=match.get('score', 0.0),
                        )
                        mapping_count += 1

                    except Exception as e:
                        logger.warning(f"Error creating mapping for product {product_id}: {e}")

            logger.info(f"Created {mapping_count} mappings for object {detected_object.id}")

        # 3. ImageAnalysis 상태 업데이트
        analysis.image_analysis_status = ImageAnalysis.Status.DONE
        analysis.save()

        logger.info(f"Successfully saved {len(results)} results for analysis {analysis_id}")

    except ImageAnalysis.DoesNotExist:
        logger.error(f"ImageAnalysis {analysis_id} not found")
    except Exception as e:
        logger.error(f"Failed to save analysis results: {e}")


# =============================================================================
# Refine Analysis Tasks (자연어 기반 재분석 - 병렬 처리)
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
        # 파싱 실패 시 기본값 반환
        return {
            'action': 'research',
            'target_categories': available_categories,
            'search_keywords': None,
            'brand_filter': None,
            'price_filter': None,
            'style_keywords': [],
        }


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

    Args:
        refine_id: 재분석 작업 ID (UUID)
        analysis_id: 원본 분석 ID
        target_object_ids: 재검색 대상 DetectedObject ID 목록
        parsed_query: LangChain으로 파싱된 쿼리 정보
            - action: 'research' | 'filter' | 'change_category'
            - target_categories: 대상 카테고리 목록
            - search_keywords: 추가 검색 키워드
            - style_keywords: 스타일 키워드 목록

    Returns:
        재분석 결과
    """
    from celery import group, chord
    from analyses.models import ImageAnalysis

    redis_service = get_redis_service()

    try:
        # 1. 상태 업데이트: RUNNING
        redis_service.set(f"refine:{refine_id}:status", "RUNNING", ttl=3600)
        redis_service.set(f"refine:{refine_id}:progress", "0", ttl=3600)
        redis_service.set(f"refine:{refine_id}:total", str(len(target_object_ids)), ttl=3600)

        logger.info(f"Starting refine analysis {refine_id} for {len(target_object_ids)} objects")

        # 2. 각 객체별 서브태스크 생성
        subtasks = []
        for obj_id in target_object_ids:
            subtasks.append(
                refine_single_object.s(
                    refine_id=refine_id,
                    detected_object_id=obj_id,
                    parsed_query=parsed_query,
                )
            )

        # 3. Celery Group으로 병렬 실행 후 결과 수집
        # chord: 병렬 실행 후 콜백 태스크 실행
        callback = refine_analysis_complete.s(refine_id=refine_id, analysis_id=analysis_id)
        job = chord(subtasks)(callback)

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
    외부 API 호출 (임베딩 생성, OpenSearch 검색)을 수행합니다.

    Args:
        refine_id: 재분석 작업 ID
        detected_object_id: DetectedObject ID
        parsed_query: 파싱된 쿼리 정보

    Returns:
        재검색 결과 (성공/실패, 매칭된 상품 수)
    """
    from analyses.models import DetectedObject, ObjectProductMapping
    from products.models import Product

    redis_service = get_redis_service()
    embedding_service = get_embedding_service()
    opensearch_service = OpenSearchService()

    try:
        # 1. DetectedObject 조회
        detected_obj = DetectedObject.objects.get(id=detected_object_id, is_deleted=False)

        # 2. 검색 텍스트 구성
        search_keywords = parsed_query.get('search_keywords')
        style_keywords = parsed_query.get('style_keywords', [])

        if search_keywords or style_keywords:
            # 텍스트 기반 검색
            search_text = ' '.join(filter(None, [
                detected_obj.object_category,
                search_keywords,
                ' '.join(style_keywords) if style_keywords else None,
            ]))
        else:
            # 기본 카테고리 기반 검색
            search_text = detected_obj.object_category

        # 3. 텍스트 임베딩 생성 (외부 API 호출)
        embedding = embedding_service.get_text_embedding(search_text)

        # 4. OpenSearch 검색 (외부 API 호출)
        category_mapping = {
            'bottom': 'pants',
            'outerwear': 'outer',
        }
        search_category = category_mapping.get(
            detected_obj.object_category, detected_obj.object_category
        )

        search_results = opensearch_service.search_similar_products_hybrid(
            embedding=embedding,
            category=search_category,
            k=5,
            search_k=50,
        )

        # 5. 기존 매핑 삭제 및 새 매핑 생성
        updated_count = 0
        if search_results:
            # 기존 매핑 soft delete
            ObjectProductMapping.objects.filter(
                detected_object=detected_obj,
                is_deleted=False
            ).update(is_deleted=True)

            # 새 매핑 생성 (Product 자동 생성 포함)
            for result in search_results:
                product_id = result.get('product_id')
                if product_id:
                    try:
                        # 1. 기존 Product 검색
                        product = Product.objects.filter(
                            product_url__endswith=f'/{product_id}'
                        ).first()

                        # 2. 없으면 OpenSearch 결과로 자동 생성
                        if not product:
                            product, created = Product.objects.update_or_create(
                                product_url=f'https://www.musinsa.com/app/goods/{product_id}',
                                defaults={
                                    'brand_name': result.get('brand', 'Unknown'),
                                    'product_name': result.get('name', 'Unknown'),
                                    'category': result.get('category', detected_obj.object_category),
                                    'selling_price': int(result.get('price', 0) or 0),
                                    'product_image_url': result.get('image_url', ''),
                                }
                            )
                            if created:
                                logger.info(f"Auto-created Product {product_id}: {result.get('name', '')[:30]}")

                        # 3. 매핑 생성
                        ObjectProductMapping.objects.create(
                            detected_object=detected_obj,
                            product=product,
                            confidence_score=result.get('score', 0.0),
                        )
                        updated_count += 1

                    except Exception as e:
                        logger.warning(f"Error creating mapping for product {product_id}: {e}")

        # 6. 진행률 업데이트
        current = redis_service.get(f"refine:{refine_id}:completed") or "0"
        redis_service.set(f"refine:{refine_id}:completed", str(int(current) + 1), ttl=3600)

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
    최종 상태를 업데이트하고 결과를 집계합니다.

    Args:
        results: 각 서브태스크의 결과 목록
        refine_id: 재분석 작업 ID
        analysis_id: 원본 분석 ID

    Returns:
        최종 결과 요약
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
# Virtual Fitting Tasks
# =============================================================================

@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def process_virtual_fitting(
    self,
    fitting_id: str,
    model_image_url: str,
    garment_image_url: str,
    category: str = 'tops',
):
    """
    Process virtual fitting request.

    Args:
        fitting_id: Fitting job ID
        model_image_url: URL of model/person image
        garment_image_url: URL of garment image
        category: Garment category

    Returns:
        Fitting result
    """
    from services.fashn_service import get_fashn_service

    redis_service = get_redis_service()

    try:
        redis_service.set(f"fitting:{fitting_id}:status", "RUNNING", ttl=3600)

        fashn_service = get_fashn_service()
        result = fashn_service.create_fitting_and_wait(
            model_image_url=model_image_url,
            garment_image_url=garment_image_url,
            category=category,
        )

        if result.status == 'completed':
            redis_service.set(f"fitting:{fitting_id}:status", "DONE", ttl=3600)
            redis_service.set(
                f"fitting:{fitting_id}:result",
                result.output_url or '',
                ttl=3600,
            )
            return {'fitting_id': fitting_id, 'output_url': result.output_url}
        else:
            redis_service.set(f"fitting:{fitting_id}:status", "FAILED", ttl=3600)
            return {'fitting_id': fitting_id, 'error': result.error}

    except Exception as e:
        logger.error(f"Fitting {fitting_id} failed: {e}")
        redis_service.set(f"fitting:{fitting_id}:status", "FAILED", ttl=3600)
        raise self.retry(exc=e)


# =============================================================================
# Image Upload Tasks (GCS 업로드 - 비동기 처리)
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def upload_image_to_gcs_task(
    self,
    image_b64: str,
    filename: str,
    content_type: str,
    user_id: int = None,
):
    """
    이미지를 GCS에 업로드하는 Celery 태스크.

    외부 API 호출: Google Cloud Storage

    Args:
        image_b64: Base64 인코딩된 이미지 데이터
        filename: 원본 파일명
        content_type: MIME 타입 (image/jpeg, image/png 등)
        user_id: 업로드한 사용자 ID (optional)

    Returns:
        업로드 결과 (uploaded_image_id, url, created_at)
    """
    import base64
    import uuid
    from datetime import datetime
    from django.conf import settings
    from django.core.files.base import ContentFile
    from google.cloud import storage
    from analyses.models import UploadedImage

    try:
        # 1. Base64 디코딩
        image_bytes = base64.b64decode(image_b64)

        # 2. 고유한 파일명 생성
        ext = filename.split('.')[-1] if '.' in filename else 'jpg'
        unique_filename = f"uploads/{datetime.now().strftime('%Y/%m/%d')}/{uuid.uuid4()}.{ext}"

        # 3. GCS에 직접 업로드
        client = storage.Client()
        bucket_name = settings.GCS_BUCKET_NAME
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(unique_filename)

        blob.upload_from_string(
            image_bytes,
            content_type=content_type,
        )

        # 4. Public URL 생성
        gcs_url = f"https://storage.googleapis.com/{bucket_name}/{unique_filename}"

        # 5. DB에 레코드 생성
        from users.models import User
        user = None
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                pass

        uploaded_image = UploadedImage.objects.create(
            user=user,
            uploaded_image_url=unique_filename,  # GCS 경로 저장
        )

        logger.info(f"Image uploaded to GCS: {gcs_url}")

        return {
            'uploaded_image_id': uploaded_image.id,
            'uploaded_image_url': gcs_url,
            'created_at': uploaded_image.created_at.isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to upload image to GCS: {e}")
        raise self.retry(exc=e)
