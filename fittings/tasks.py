from celery import shared_task
import logging
from .models import Fitting
from services.fashn_service import get_fashn_service

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_fitting_task(self, fitting_id):
    """
    Fashn.ai API를 사용하여 가상 피팅을 비동기로 처리하고 
    결과를 DB의 fitting_image_url 필드에 저장합니다.
    """
    try:
        # 1. DB에서 피팅 객체 가져오기
        fitting = Fitting.objects.get(id=fitting_id)
        
        # 상태를 처리 중(processing)으로 업데이트
        fitting.fitting_image_status = 'processing'
        fitting.save()

        # 2. 서비스 인스턴스 확보
        service = get_fashn_service()

        # 3. API 호출 및 대기 (Polling)
        # model_image_url 대신 알려주신 user_image_url 필드를 사용합니다.
        # garment_image_url과 category는 모델에 해당 이름으로 있다고 가정했습니다.
        result = service.create_fitting_and_wait(
            model_image_url=fitting.user_image_url,
            garment_image_url=fitting.garment_image_url,
            category=service.map_category(fitting.category)
        )

        # 4. 결과값에 따른 상태 및 URL 업데이트
        if result.status == 'completed':
            fitting.fitting_image_status = 'completed'
            fitting.fitting_image_url = result.output_url  # 결과 이미지 주소 저장
            logger.info(f"Fitting {fitting_id} 완료: {result.output_url}")
        else:
            fitting.fitting_image_status = 'failed'
            # 서비스 코드에서 정의한 에러 메시지가 있다면 활용 가능합니다.
            logger.error(f"Fitting {fitting_id} 실패: {result.error}")

        fitting.save()

    except Exception as exc:
        logger.error(f"Fitting {fitting_id} 처리 중 시스템 에러 발생: {exc}")
        # 예외 발생 시 DB 상태를 실패로 변경
        try:
            fitting = Fitting.objects.get(id=fitting_id)
            fitting.fitting_image_status = 'failed'
            fitting.save()
        except:
            pass
        # Celery 재시도 설정 (네트워크 오류 등 대비)
        raise self.retry(exc=exc, countdown=60)