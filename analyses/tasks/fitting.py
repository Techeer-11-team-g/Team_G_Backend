"""
Virtual Fitting Tasks - 가상 피팅 처리.

DEPRECATED: 이 모듈은 현재 사용되지 않습니다.
실제 피팅 처리는 fittings/tasks.py의 process_fitting_task를 사용합니다.
이 모듈은 하위 호환성을 위해 유지되며, 향후 제거될 예정입니다.
"""

import logging
import warnings

from celery import shared_task

from services.redis_service import get_redis_service, RedisService

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

    DEPRECATED: 이 태스크는 현재 사용되지 않습니다.
    실제 피팅은 fittings/tasks.py의 process_fitting_task를 사용하세요.

    Args:
        fitting_id: Fitting job ID
        model_image_url: URL of model/person image
        garment_image_url: URL of garment image
        category: Garment category

    Returns:
        Fitting result
    """
    warnings.warn(
        "process_virtual_fitting is deprecated. Use fittings.tasks.process_fitting_task instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    from services.fashn_service import get_fashn_service

    redis_service = get_redis_service()

    try:
        redis_service.set(f"fitting:{fitting_id}:status", "RUNNING", ttl=RedisService.TTL_POLLING)

        fashn_service = get_fashn_service()
        result = fashn_service.create_fitting_and_wait(
            model_image_url=model_image_url,
            garment_image_url=garment_image_url,
            category=category,
        )

        if result.status == 'completed':
            redis_service.set(f"fitting:{fitting_id}:status", "DONE", ttl=RedisService.TTL_POLLING)
            redis_service.set(
                f"fitting:{fitting_id}:result",
                result.output_url or '',
                ttl=RedisService.TTL_POLLING,
            )
            return {'fitting_id': fitting_id, 'output_url': result.output_url}
        else:
            redis_service.set(f"fitting:{fitting_id}:status", "FAILED", ttl=RedisService.TTL_POLLING)
            return {'fitting_id': fitting_id, 'error': result.error}

    except Exception as e:
        logger.error(f"Fitting {fitting_id} failed: {e}")
        redis_service.set(f"fitting:{fitting_id}:status", "FAILED", ttl=RedisService.TTL_POLLING)
        raise self.retry(exc=e)
