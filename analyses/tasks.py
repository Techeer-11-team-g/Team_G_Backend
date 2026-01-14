"""
Celery Tasks for Image Analysis Pipeline.

Pipeline:
1. Receive image analysis request
2. Google Vision API for object detection (bbox)
3. Crop detected items with padding
4. Generate embeddings using FashionCLIP
5. Hybrid search in OpenSearch (k-NN + keyword)
6. BLIP + CLIP re-ranking for better accuracy
7. Save results to MySQL
8. Update status in Redis
"""

import io
import logging
from typing import Optional

from celery import shared_task
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
    Main task for processing image analysis.

    Args:
        analysis_id: Analysis job ID
        image_url: GCS URL of the uploaded image
        user_id: Optional user ID

    Returns:
        Analysis result dict
    """
    redis_service = get_redis_service()

    try:
        # Update status to RUNNING
        redis_service.update_analysis_running(analysis_id, progress=0)
        logger.info(f"Starting analysis {analysis_id}")

        # Step 1: Download image from GCS
        redis_service.set_analysis_progress(analysis_id, 10)
        image_bytes = _download_image(image_url)

        # Step 2: Detect objects with Vision API
        redis_service.set_analysis_progress(analysis_id, 20)
        detected_items = _detect_objects(image_bytes)
        logger.info(f"Detected {len(detected_items)} items")

        if not detected_items:
            redis_service.update_analysis_done(analysis_id, {'items': []})
            return {'analysis_id': analysis_id, 'items': []}

        # Step 3: Process each detected item
        results = []
        progress_per_item = 60 / len(detected_items)  # 20-80% for item processing

        for idx, item in enumerate(detected_items):
            current_progress = 20 + int((idx + 1) * progress_per_item)
            redis_service.set_analysis_progress(analysis_id, current_progress)

            # Process individual item
            item_result = _process_detected_item(
                analysis_id=analysis_id,
                image_bytes=image_bytes,
                detected_item=item,
                item_index=idx,
            )
            if item_result:
                results.append(item_result)

        # Step 4: Save results to database
        redis_service.set_analysis_progress(analysis_id, 90)
        _save_analysis_results(analysis_id, results, user_id)

        # Step 5: Mark as complete
        redis_service.update_analysis_done(analysis_id, {'items': results})
        logger.info(f"Analysis {analysis_id} completed with {len(results)} items")

        return {'analysis_id': analysis_id, 'items': results}

    except Exception as e:
        logger.error(f"Analysis {analysis_id} failed: {e}")
        redis_service.update_analysis_failed(analysis_id, str(e))

        # Retry on transient errors
        raise self.retry(exc=e)


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
    - analyses table: status = DONE
    - detected_items table: insert detected items
    - product_matches table: insert top matches
    """
    # This will be implemented when Django models are created
    # For now, just log
    logger.info(f"Saving {len(results)} results for analysis {analysis_id}")


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
