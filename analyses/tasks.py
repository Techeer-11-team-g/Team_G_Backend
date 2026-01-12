"""
Celery Tasks for Image Analysis Pipeline.

Pipeline:
1. Receive image analysis request
2. Google Vision API for object detection (bbox)
3. Crop detected items and upload to GCS
4. Generate embeddings using OpenAI
5. Search similar products in OpenSearch k-NN
6. Evaluate results with LangChain
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
from services.redis_service import get_redis_service, AnalysisStatus
from services.langchain_service import LangChainService

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
        # Step 1: Crop image
        cropped_bytes = _crop_image(image_bytes, detected_item)

        # Step 2: Upload to GCS
        crop_url = _upload_crop_to_gcs(analysis_id, item_index, cropped_bytes)

        # Step 3: Generate embedding
        embedding_service = get_embedding_service()
        embedding = embedding_service.get_image_embedding(cropped_bytes)

        # Step 4: Search similar products
        opensearch_service = OpenSearchService()
        search_results = opensearch_service.search_similar_products(
            embedding=embedding,
            k=5,
            category=detected_item.category,
        )

        if not search_results:
            logger.warning(f"No matching products found for item {item_index}")
            return None

        # Step 5: Evaluate with LangChain (optional quality check)
        top_match = search_results[0]
        evaluated = _evaluate_match(detected_item, top_match)

        return {
            'index': item_index,
            'category': detected_item.category,
            'bbox': detected_item.bbox.to_dict(),
            'confidence': detected_item.confidence,
            'crop_url': crop_url,
            'product_id': top_match['product_id'],
            'match_score': top_match['score'],
            'evaluation': evaluated,
        }

    except Exception as e:
        logger.error(f"Failed to process item {item_index}: {e}")
        return None


def _crop_image(image_bytes: bytes, item: DetectedItem) -> bytes:
    """Crop detected item from image."""
    image = Image.open(io.BytesIO(image_bytes))
    width, height = image.size

    # Convert normalized coordinates to pixels
    bbox = item.bbox
    x_min = int(bbox.x_min * width / 1000)
    y_min = int(bbox.y_min * height / 1000)
    x_max = int(bbox.x_max * width / 1000)
    y_max = int(bbox.y_max * height / 1000)

    # Crop
    cropped = image.crop((x_min, y_min, x_max, y_max))

    # Convert to bytes
    output = io.BytesIO()
    cropped.save(output, format='JPEG', quality=90)
    return output.getvalue()


def _upload_crop_to_gcs(analysis_id: str, item_index: int, image_bytes: bytes) -> str:
    """Upload cropped image to GCS."""
    from google.cloud import storage

    bucket_name = getattr(settings, 'GCS_BUCKET_NAME', '')
    if not bucket_name:
        logger.warning("GCS_BUCKET_NAME not configured, skipping upload")
        return ''

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    blob_name = f"crops/{analysis_id}/{item_index}.jpg"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(image_bytes, content_type='image/jpeg')

    return f"gs://{bucket_name}/{blob_name}"


def _evaluate_match(detected_item: DetectedItem, match: dict) -> dict:
    """
    Evaluate match quality using LangChain.

    Args:
        detected_item: Detected item
        match: Search result match

    Returns:
        Evaluation result
    """
    try:
        langchain_service = LangChainService()
        evaluation = langchain_service.evaluate_search_result(
            category=detected_item.category,
            confidence=detected_item.confidence,
            match_score=match['score'],
            product_id=match['product_id'],
        )
        return evaluation
    except Exception as e:
        logger.warning(f"LangChain evaluation failed: {e}")
        return {'quality': 'unknown', 'reason': str(e)}


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
