"""
Virtual Fitting Tasks - 가상 피팅 처리.
"""

import logging

from celery import shared_task

from services.redis_service import get_redis_service

logger = logging.getLogger(__name__)


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
        # (Redis 임시 저장: 피팅 진행 상태, 1시간 TTL)
        redis_service.set(f"fitting:{fitting_id}:status", "RUNNING", ttl=3600)

        fashn_service = get_fashn_service()
        result = fashn_service.create_fitting_and_wait(
            model_image_url=model_image_url,
            garment_image_url=garment_image_url,
            category=category,
        )

        if result.status == 'completed':
            # (Redis 임시 저장: 완료 상태 및 결과 이미지 URL)
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
        # (Redis 임시 저장: 실패 상태)
        redis_service.set(f"fitting:{fitting_id}:status", "FAILED", ttl=3600)
        raise self.retry(exc=e)
