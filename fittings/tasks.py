import logging
from celery import shared_task
from .models import FittingImage
from services.fashn_service import get_fashn_service

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_fitting_task(self, fitting_id):
    try:
        fitting = FittingImage.objects.select_related('user_image', 'product').get(id=fitting_id)
        fitting.fitting_image_status = FittingImage.Status.RUNNING
        fitting.save(update_fields=['fitting_image_status', 'updated_at'])

        service = get_fashn_service()
        category = service.map_category(fitting.product.category)

        logger.info(f"Fitting {fitting_id}: category={fitting.product.category} -> {category}")

        # The New Black API는 동기식 - 즉시 결과 반환 (폴링 불필요)
        result = service.create_fitting_with_files(
            model_image=fitting.user_image.user_image_url,
            garment_image=fitting.product.product_image_url,
            category=category
        )

        if result.status == 'completed' and result.output_url:
            fitting.fitting_image_status = FittingImage.Status.DONE
            fitting.fitting_image_url = result.output_url
            logger.info(f"Fitting {fitting_id}: completed - {result.output_url[:60]}...")
        else:
            fitting.fitting_image_status = FittingImage.Status.FAILED
            logger.error(f"Fitting {fitting_id}: failed - {result.error}")

        fitting.save(update_fields=['fitting_image_status', 'fitting_image_url', 'updated_at'])

    except Exception as exc:
        logger.exception(f"Fitting {fitting_id}: exception occurred")
        FittingImage.objects.filter(id=fitting_id).update(fitting_image_status=FittingImage.Status.FAILED)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))  # Exponential backoff