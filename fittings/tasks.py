from celery import shared_task
from .models import FittingImage
from services.fashn_service import get_fashn_service

@shared_task(bind=True, max_retries=3)
def process_fitting_task(self, fitting_id):
    try:
        # DB에서 관계된 모델들(user_image, product)을 한꺼번에 가져옴
        fitting = FittingImage.objects.select_related('user_image', 'product').get(id=fitting_id)
        fitting.fitting_image_status = FittingImage.Status.RUNNING
        fitting.save()

        service = get_fashn_service()

        # 우리 DB 필드명에 맞춰 URL 추출 후 전달
        result = service.create_fitting_and_wait(
            model_image_url=fitting.user_image.user_image_url,
            product_image_url=fitting.product.product_image_url,
            category=service.map_category(fitting.product.size_group.category)
        )

        if result.status == 'completed':
            fitting.fitting_image_status = FittingImage.Status.DONE
            fitting.fitting_image_url = result.output_url
        else:
            fitting.fitting_image_status = FittingImage.Status.FAILED
        
        fitting.save()

    except Exception as exc:
        FittingImage.objects.filter(id=fitting_id).update(fitting_image_status=FittingImage.Status.FAILED)
        raise self.retry(exc=exc, countdown=60)