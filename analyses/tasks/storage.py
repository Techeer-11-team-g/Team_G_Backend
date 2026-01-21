"""
Storage Operations - GCS 업로드/다운로드 유틸리티.

이 모듈은 Google Cloud Storage와의 상호작용을 담당합니다:
- 이미지 다운로드 (GCS, HTTP, 로컬 파일)
- 크롭된 이미지 업로드
- 트레이싱 지원

Usage:
    from analyses.tasks.storage import download_image, upload_cropped_image
"""

import logging
from datetime import datetime
from typing import Optional

from django.conf import settings
from google.cloud import storage

from analyses.utils import create_span


logger = logging.getLogger(__name__)

# 트레이서 모듈명
TRACER_NAME = "analyses.tasks.storage"


def download_image(image_url: str) -> bytes:
    """
    URL에서 이미지를 다운로드.

    지원 형식:
    - GCS URL (gs://, https://storage.googleapis.com/)
    - HTTP/HTTPS URL
    - 로컬 파일 경로 (/media/)

    Args:
        image_url: 이미지 URL 또는 경로

    Returns:
        이미지 바이트 데이터

    Raises:
        ValueError: 지원하지 않는 URL 형식
        FileNotFoundError: 로컬 파일이 존재하지 않음
    """
    import os

    # GCS HTTPS URL을 gs:// 형식으로 변환
    if 'storage.googleapis.com' in image_url:
        parts = image_url.split('storage.googleapis.com/')
        if len(parts) > 1:
            image_url = 'gs://' + parts[1]

    if image_url.startswith('gs://'):
        return _download_from_gcs(image_url)

    elif image_url.startswith('/media/'):
        return _download_from_local(image_url)

    elif image_url.startswith('http://') or image_url.startswith('https://'):
        return _download_from_http(image_url)

    else:
        raise ValueError(f"Unsupported URL format: {image_url}")


def _download_from_gcs(gcs_url: str) -> bytes:
    """GCS에서 이미지 다운로드."""
    parts = gcs_url[5:].split('/', 1)
    bucket_name = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ''

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    return blob.download_as_bytes()


def _download_from_local(media_path: str) -> bytes:
    """로컬 파일에서 이미지 다운로드."""
    import os

    local_path = settings.BASE_DIR / media_path.lstrip('/')
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Local file not found: {local_path}")

    with open(local_path, 'rb') as f:
        return f.read()


def _download_from_http(url: str) -> bytes:
    """HTTP URL에서 이미지 다운로드."""
    import requests

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.content


def upload_cropped_image(
    image_bytes: bytes,
    analysis_id: str,
    item_index: int,
    category: str,
) -> Optional[str]:
    """
    크롭된 이미지를 GCS에 업로드.

    Args:
        image_bytes: 이미지 바이트 데이터
        analysis_id: 분석 ID
        item_index: 아이템 인덱스
        category: 카테고리명

    Returns:
        GCS URL 또는 None (업로드 실패 시)
    """
    try:
        bucket_name = settings.GCS_BUCKET_NAME
        credentials_file = settings.GCS_CREDENTIALS_FILE

        if not bucket_name or not credentials_file:
            logger.warning("GCS not configured, skipping upload")
            return None

        client = storage.Client.from_service_account_json(credentials_file)
        bucket = client.bucket(bucket_name)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"cropped/{analysis_id}/{timestamp}_{item_index}_{category}.jpg"

        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type='image/jpeg')

        gcs_url = f"https://storage.googleapis.com/{bucket_name}/{filename}"
        logger.info(f"Uploaded cropped image to GCS: {gcs_url}")

        return gcs_url

    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}")
        return None


def upload_cropped_image_with_span(
    image_bytes: bytes,
    analysis_id: str,
    item_index: int,
    category: str,
) -> Optional[str]:
    """
    크롭된 이미지를 GCS에 업로드 (트레이싱 포함).

    병렬 실행 시 트레이스 컨텍스트를 유지하며 업로드합니다.

    Args:
        image_bytes: 이미지 바이트 데이터
        analysis_id: 분석 ID
        item_index: 아이템 인덱스
        category: 카테고리명

    Returns:
        GCS URL 또는 None
    """
    with create_span(TRACER_NAME, "2_upload_to_gcs") as span:
        span.set("service", "google_cloud_storage")
        span.set("analysis_id", analysis_id)
        span.set("item_index", item_index)
        return upload_cropped_image(
            image_bytes=image_bytes,
            analysis_id=analysis_id,
            item_index=item_index,
            category=category,
        )
