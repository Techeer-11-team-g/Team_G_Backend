"""
Image Analysis Tasks - 이미지 분석 파이프라인.

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

비동기 처리:
- RabbitMQ: 메시지 브로커로 태스크 큐잉
- Celery Group: 여러 객체를 병렬로 처리
- Redis: 진행 상태 및 결과 캐싱
"""

import io
import base64
import logging
import uuid
from datetime import datetime
from typing import Optional

from celery import shared_task, chord
from django.conf import settings
from PIL import Image
from google.cloud import storage

from services.vision_service import get_vision_service, DetectedItem
from services.embedding_service import get_embedding_service
from services.opensearch_client import OpenSearchService
from services.redis_service import get_redis_service
from services.metrics import (
    ANALYSIS_TOTAL,
    ANALYSIS_DURATION,
    ANALYSIS_IN_PROGRESS,
    ANALYSES_COMPLETED_TOTAL,
    PRODUCT_MATCHES_TOTAL,
    push_metrics,
)

logger = logging.getLogger(__name__)


def _upload_to_gcs(image_bytes: bytes, analysis_id: str, item_index: int, category: str) -> Optional[str]:
    """
    Upload cropped image to GCS.

    Args:
        image_bytes: Cropped image bytes
        analysis_id: Analysis job ID
        item_index: Item index
        category: Item category

    Returns:
        GCS public URL or None if upload fails
    """
    try:
        bucket_name = settings.GCS_BUCKET_NAME
        credentials_file = settings.GCS_CREDENTIALS_FILE

        if not bucket_name or not credentials_file:
            logger.warning("GCS not configured, skipping upload")
            return None

        # Create storage client
        client = storage.Client.from_service_account_json(credentials_file)
        bucket = client.bucket(bucket_name)

        # Generate unique filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"cropped/{analysis_id}/{timestamp}_{item_index}_{category}.jpg"

        # Upload
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type='image/jpeg')

        # Return public URL
        gcs_url = f"https://storage.googleapis.com/{bucket_name}/{filename}"
        logger.info(f"Uploaded cropped image to GCS: {gcs_url}")

        return gcs_url

    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}")
        return None


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
    redis_service = get_redis_service()
    ANALYSIS_IN_PROGRESS.inc()

    try:
        # Update status to RUNNING
        redis_service.update_analysis_running(analysis_id, progress=0)
        logger.info(f"Starting analysis {analysis_id}")

        # Step 1: Download image from GCS
        redis_service.set_analysis_progress(analysis_id, 10)
        with ANALYSIS_DURATION.labels(stage='download_image').time():
            image_bytes = _download_image(image_url)

        # Step 2: Detect objects with Vision API (외부 API 호출)
        redis_service.set_analysis_progress(analysis_id, 20)
        with ANALYSIS_DURATION.labels(stage='detect_objects').time():
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
    - Claude Vision: 속성 추출 (color, brand, style)
    - FashionCLIP: 이미지 임베딩 생성
    - OpenSearch: k-NN 하이브리드 검색

    Args:
        analysis_id: Analysis job ID
        image_b64: Base64 encoded image
        detected_item_dict: Detected item as dict
        item_index: Item index

    Returns:
        Processed item result
    """
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
    
    🆕 추가: 분석 완료 후 각 상품에 대해 자동 피팅 요청

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
        with ANALYSIS_DURATION.labels(stage='save_results').time():
            _save_analysis_results(analysis_id, valid_results, user_id)

        # 완료 상태 업데이트
        redis_service.update_analysis_done(analysis_id, {'items': valid_results})
        _update_analysis_status_db(analysis_id, 'DONE')

        # Metrics: 분석 완료
        ANALYSIS_TOTAL.labels(status='success').inc()
        ANALYSES_COMPLETED_TOTAL.inc()
        ANALYSIS_IN_PROGRESS.dec()

        # Metrics: 매칭된 상품 수
        for result in valid_results:
            category = result.get('category', 'unknown')
            match_count = len(result.get('matches', []))
            for _ in range(match_count):
                PRODUCT_MATCHES_TOTAL.labels(category=category).inc()

        logger.info(f"Analysis {analysis_id} completed: {len(valid_results)}/{total_items} items processed")

        # 🆕 분석 완료 후 자동 피팅 요청
        if user_id:
            _trigger_auto_fittings(analysis_id, valid_results, user_id)

        # Celery 워커 메트릭을 Pushgateway로 푸시
        push_metrics()

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

        # Metrics: 분석 실패
        ANALYSIS_TOTAL.labels(status='failed').inc()
        ANALYSIS_IN_PROGRESS.dec()

        # 실패 시에도 메트릭 푸시
        push_metrics()

        return {
            'analysis_id': analysis_id,
            'status': 'FAILED',
            'error': str(e),
        }


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


# =============================================================================
# Helper Functions
# =============================================================================

def _update_analysis_status_db(analysis_id: str, status: str):
    """DB의 ImageAnalysis 상태 업데이트 헬퍼 함수."""
    from analyses.models import ImageAnalysis
    try:
        analysis = ImageAnalysis.objects.get(id=analysis_id)
        analysis.image_analysis_status = status
        analysis.save(update_fields=['image_analysis_status', 'updated_at'])
    except ImageAnalysis.DoesNotExist:
        logger.error(f"ImageAnalysis {analysis_id} not found for status update")


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
    2. Upload to GCS
    3. Extract attributes with Claude Vision (color, brand, etc.)
    4. Generate embedding
    5. Search similar products (with attribute filtering)

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

        # Step 2: Upload cropped image to GCS
        cropped_image_url = _upload_to_gcs(
            image_bytes=cropped_bytes,
            analysis_id=analysis_id,
            item_index=item_index,
            category=detected_item.category,
        )

        # Step 3: Extract attributes with GPT-4V
        from services.gpt4v_service import get_gpt4v_service
        try:
            gpt4v_service = get_gpt4v_service()
            with ANALYSIS_DURATION.labels(stage='extract_attributes').time():
                attributes = gpt4v_service.extract_attributes(
                    image_bytes=cropped_bytes,
                    category=detected_item.category,
                )
            logger.info(f"Item {item_index} - GPT-4V attributes: color={attributes.color}, secondary_color={attributes.secondary_color}, brand={attributes.brand}")
        except Exception as e:
            logger.warning(f"GPT-4V extraction failed: {e}")
            attributes = None

        # Step 4: Generate embedding
        embedding_service = get_embedding_service()
        with ANALYSIS_DURATION.labels(stage='generate_embedding').time():
            embedding = embedding_service.get_image_embedding(cropped_bytes)

        # Step 5: Search similar products
        # Vision API 카테고리 → OpenSearch 카테고리 매핑
        category_mapping = {
            'bottom': 'pants',
            'outerwear': 'outer',
        }
        search_category = category_mapping.get(detected_item.category, detected_item.category)

        opensearch_service = OpenSearchService()

        # 브랜드 또는 색상이 감지되면 속성 기반 검색, 아니면 하이브리드 검색
        detected_brand = attributes.brand if attributes else None
        detected_color = attributes.color if attributes else None
        detected_secondary = attributes.secondary_color if attributes else None

        if detected_brand or detected_color:
            logger.info(f"Item {item_index} - Using attribute search (brand={detected_brand}, color={detected_color}, secondary={detected_secondary})")
            with ANALYSIS_DURATION.labels(stage='search_products').time():
                search_results = opensearch_service.search_with_attributes(
                    embedding=embedding,
                    category=search_category,
                    brand=detected_brand,
                    color=detected_color,
                    secondary_color=detected_secondary,
                    k=30,
                    search_k=400,
                )
        else:
            # 속성 없으면 기존 하이브리드 검색
            logger.info(f"Item {item_index} - No attributes, using hybrid search")
            with ANALYSIS_DURATION.labels(stage='search_products').time():
                search_results = opensearch_service.search_similar_products_hybrid(
                    embedding=embedding,
                    category=search_category,
                    k=30,
                    search_k=400,
                )

        if not search_results:
            logger.warning(f"No matching products found for item {item_index}")
            return None

        # Claude 리랭킹으로 정확도 향상
        from services.gpt4v_service import get_gpt4v_service
        try:
            gpt4v_service = get_gpt4v_service()
            with ANALYSIS_DURATION.labels(stage='rerank_products').time():
                search_results = gpt4v_service.rerank_products(
                    query_image_bytes=cropped_bytes,
                    candidates=search_results[:10],  # 상위 10개만 리랭킹
                    top_k=5,
                )
            logger.info(f"Item {item_index} - Claude reranking completed")
        except Exception as e:
            logger.warning(f"Claude reranking failed, using original results: {e}")
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

        # 결과에 추출된 속성 정보 포함
        result = {
            'index': item_index,
            'category': detected_item.category,
            'bbox': pixel_bbox,
            'confidence': detected_item.confidence,
            'cropped_image_url': cropped_image_url,  # GCS URL
            'matches': top_matches,  # 상위 5개
        }

        # GPT-4V 속성 추가 (있으면)
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


def _trigger_auto_fittings(analysis_id: str, results: list[dict], user_id: int):
    """
    분석 완료 후 자동 피팅 요청 트리거.
    
    사용자의 전신 이미지와 각 매칭된 상품에 대해
    자동으로 피팅 태스크를 실행합니다.
    
    Args:
        analysis_id: Analysis job ID
        results: 분석 결과 (각 검출 객체와 매칭된 상품들)
        user_id: 사용자 ID
    """
    from fittings.models import UserImage, FittingImage
    from fittings.tasks import process_fitting_task
    from products.models import Product
    
    try:
        # 1. 사용자의 전신 이미지 조회 (가장 최근 것)
        user_image = UserImage.objects.filter(
            user_id=user_id,
            is_deleted=False
        ).order_by('-created_at').first()
        
        if not user_image:
            logger.warning(f"User {user_id} has no body image, skipping auto-fitting")
            return
        
        logger.info(f"Auto-fitting: Found user image {user_image.id} for user {user_id}")
        
        # 2. 각 검출 객체의 상위 매칭 상품에 대해 피팅 요청
        fitting_count = 0
        for result in results:
            matches = result.get('matches', [])
            if not matches:
                continue
            
            # 상위 1개 상품에 대해서만 피팅 (필요시 조정 가능)
            top_match = matches[0]
            product_id = top_match.get('product_id')
            
            if not product_id:
                continue
            
            try:
                # Product 조회
                product = Product.objects.filter(
                    product_url__endswith=f'/{product_id}'
                ).first()
                
                if not product:
                    logger.warning(f"Product {product_id} not found, skipping")
                    continue
                
                # 이미 피팅이 존재하는지 확인 (중복 방지)
                existing_fitting = FittingImage.objects.filter(
                    user_image=user_image,
                    product=product,
                    is_deleted=False
                ).first()
                
                if existing_fitting:
                    logger.info(f"Fitting already exists for product {product.id}, skipping")
                    continue
                
                # FittingImage 생성 (PENDING 상태)
                fitting = FittingImage.objects.create(
                    user_image=user_image,
                    product=product,
                    fitting_image_status=FittingImage.Status.PENDING,
                )
                
                # 피팅 태스크 비동기 실행
                process_fitting_task.delay(fitting.id)
                fitting_count += 1
                
                logger.info(f"Auto-fitting triggered: FittingImage {fitting.id} for product {product.id}")
                
            except Exception as e:
                logger.error(f"Failed to trigger fitting for product {product_id}: {e}")
        
        logger.info(f"Auto-fitting completed: {fitting_count} fittings triggered for analysis {analysis_id}")
        
    except Exception as e:
        logger.error(f"Failed to trigger auto-fittings for analysis {analysis_id}: {e}")

