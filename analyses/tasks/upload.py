"""
Image Upload Tasks - GCS 업로드 비동기 처리.
"""

import base64
import uuid
import logging
from datetime import datetime

from celery import shared_task
from django.conf import settings
from google.cloud import storage

# OpenTelemetry for custom tracing spans
def _get_tracer():
    """Get tracer lazily to ensure TracerProvider is initialized."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("analyses.tasks.upload")
    except ImportError:
        return None


logger = logging.getLogger(__name__)


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
    from analyses.models import UploadedImage
    from contextlib import nullcontext

    def create_span(name):
        tracer = _get_tracer()
        if tracer:
            return tracer.start_as_current_span(name)
        return nullcontext()

    try:
        with create_span("task_upload_image_to_gcs") as main_span:
            if main_span and hasattr(main_span, 'set_attribute'):
                main_span.set_attribute("filename", filename)
                main_span.set_attribute("content_type", content_type)

            # 1. Base64 디코딩
            with create_span("decode_base64") as span:
                image_bytes = base64.b64decode(image_b64)
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("image_size_bytes", len(image_bytes))

            # 2. 고유한 파일명 생성
            ext = filename.split('.')[-1] if '.' in filename else 'jpg'
            unique_filename = f"uploads/{datetime.now().strftime('%Y/%m/%d')}/{uuid.uuid4()}.{ext}"

            # 3. GCS에 직접 업로드
            with create_span("upload_to_gcs") as span:
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("service", "google_cloud_storage")
                    span.set_attribute("bucket", settings.GCS_BUCKET_NAME)
                    span.set_attribute("blob_path", unique_filename)

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
            with create_span("save_to_database") as span:
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("service", "mysql")

                from users.models import User
                user = None
                if user_id:
                    try:
                        user = User.objects.get(id=user_id)
                    except User.DoesNotExist:
                        pass

                uploaded_image = UploadedImage.objects.create(
                    user=user,
                    uploaded_image_url=unique_filename,
                )

                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("uploaded_image_id", uploaded_image.id)

            logger.info(f"Image uploaded to GCS: {gcs_url}")

            if main_span and hasattr(main_span, 'set_attribute'):
                main_span.set_attribute("uploaded_image_id", uploaded_image.id)
                main_span.set_attribute("gcs_url", gcs_url)

            return {
                'uploaded_image_id': uploaded_image.id,
                'uploaded_image_url': gcs_url,
                'created_at': uploaded_image.created_at.isoformat(),
            }

    except Exception as e:
        logger.error(f"Failed to upload image to GCS: {e}")
        raise self.retry(exc=e)
