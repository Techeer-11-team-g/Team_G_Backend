"""
fittings/tasks.py - 가상 피팅 Celery 태스크

이 모듈은 가상 피팅 처리를 위한 Celery 비동기 태스크를 정의합니다.

주요 기능:
    - The New Black API를 통한 가상 피팅 이미지 생성
    - Prometheus 메트릭 수집
    - OpenTelemetry 트레이싱

Task:
    - process_fitting_task: 가상 피팅 처리 태스크

Note:
    이 태스크는 FittingRequestView에서 비동기로 호출됩니다.
    실패 시 최대 3회까지 지수 백오프로 재시도합니다.
"""

import logging
from contextlib import nullcontext

from celery import shared_task

from services.fashn_service import get_fashn_service
from services.metrics import (
    FITTING_DURATION,
    FITTINGS_REQUESTED_TOTAL,
    push_metrics,
    record_api_call,
)
from .models import FittingImage

logger = logging.getLogger(__name__)


# =============================================================================
# OpenTelemetry 트레이싱 유틸리티
# =============================================================================

def _get_tracer():
    """
    OpenTelemetry Tracer를 지연 로딩합니다.
    
    Returns:
        Tracer | None: TracerProvider가 초기화된 경우 Tracer, 아니면 None
    """
    try:
        from opentelemetry import trace
        return trace.get_tracer("fittings.tasks")
    except ImportError:
        return None


def _create_span(name: str):
    """
    트레이싱 span을 생성합니다.
    
    Args:
        name: span 이름
        
    Returns:
        Span | nullcontext: Tracer가 있으면 Span, 없으면 nullcontext
    """
    tracer = _get_tracer()
    if tracer:
        return tracer.start_as_current_span(name)
    return nullcontext()


def _set_span_attr(span, key: str, value):
    """
    span에 attribute를 안전하게 설정합니다.
    
    Args:
        span: OpenTelemetry Span 객체
        key: attribute 키
        value: attribute 값
    """
    if span and hasattr(span, 'set_attribute'):
        span.set_attribute(key, value)


# =============================================================================
# Celery Tasks
# =============================================================================

@shared_task(bind=True, max_retries=3)
def process_fitting_task(self, fitting_id: int):
    """
    가상 피팅 처리 태스크
    
    The New Black API를 호출하여 가상 피팅 이미지를 생성합니다.
    
    처리 단계:
        1. DB에서 피팅 데이터 로드 및 상태를 RUNNING으로 변경
        2. 카테고리 매핑 등 피팅 파라미터 준비
        3. The New Black API 호출 (동기 방식)
        4. 결과 저장 및 상태 업데이트
    
    Args:
        fitting_id: FittingImage 레코드 ID
        
    Raises:
        Exception: API 호출 또는 처리 중 오류 발생 시.
                   최대 3회까지 지수 백오프(60초, 120초, 240초)로 재시도.
    
    Metrics:
        - FITTINGS_REQUESTED_TOTAL: 피팅 요청 수 (success/failed/error)
        - FITTING_DURATION: 피팅 처리 시간 (카테고리별)
    """
    with _create_span("process_fitting_task") as span:
        _set_span_attr(span, "fitting.id", fitting_id)

        try:
            # ----------------------------------------------------------
            # Step 1: 피팅 데이터 로드 및 상태 변경
            # ----------------------------------------------------------
            with _create_span("1_load_fitting_data"):
                fitting = FittingImage.objects.select_related(
                    'user_image', 'product'
                ).get(id=fitting_id)
                
                # 상태를 RUNNING으로 변경
                fitting.fitting_image_status = FittingImage.Status.RUNNING
                fitting.save(update_fields=['fitting_image_status', 'updated_at'])

            # ----------------------------------------------------------
            # Step 2: 피팅 파라미터 준비
            # ----------------------------------------------------------
            with _create_span("2_prepare_fitting") as prep_span:
                service = get_fashn_service()
                
                # 상품 카테고리를 The New Black API 카테고리로 매핑
                category = service.map_category(fitting.product.category)
                
                _set_span_attr(prep_span, "fitting.category", category)
                _set_span_attr(prep_span, "fitting.product_id", fitting.product.id)

            logger.info(
                f"피팅 처리 시작: id={fitting_id}, "
                f"category={fitting.product.category} -> {category}"
            )

            # ----------------------------------------------------------
            # Step 3: The New Black API 호출
            # ----------------------------------------------------------
            with _create_span("3_call_thenewblack_api") as api_span:
                # 메트릭 수집: API 호출 및 소요시간
                with record_api_call('thenewblack'):
                    with FITTING_DURATION.labels(category=category).time():
                        result = service.create_fitting_with_files(
                            model_image=fitting.user_image.user_image_url,
                            garment_image=fitting.product.product_image_url,
                            category=category
                        )
                
                _set_span_attr(api_span, "api.status", result.status)

            # ----------------------------------------------------------
            # Step 4: 결과 저장
            # ----------------------------------------------------------
            with _create_span("4_save_fitting_result"):
                if result.status == 'completed' and result.output_url:
                    # 성공
                    fitting.fitting_image_status = FittingImage.Status.DONE
                    fitting.fitting_image_url = result.output_url
                    FITTINGS_REQUESTED_TOTAL.labels(status='success').inc()
                    logger.info(
                        f"피팅 완료: id={fitting_id}, "
                        f"url={result.output_url[:60]}..."
                    )
                else:
                    # 실패 (API 응답은 왔으나 결과 없음)
                    fitting.fitting_image_status = FittingImage.Status.FAILED
                    FITTINGS_REQUESTED_TOTAL.labels(status='failed').inc()
                    logger.error(f"피팅 실패: id={fitting_id}, error={result.error}")

                fitting.save(update_fields=[
                    'fitting_image_status', 
                    'fitting_image_url', 
                    'updated_at'
                ])

            # 메트릭을 Pushgateway에 전송
            push_metrics()

        except Exception as exc:
            # ----------------------------------------------------------
            # 에러 처리 및 재시도
            # ----------------------------------------------------------
            logger.exception(f"피팅 처리 중 예외 발생: id={fitting_id}")
            FITTINGS_REQUESTED_TOTAL.labels(status='error').inc()
            push_metrics()
            
            # 상태를 FAILED로 변경
            FittingImage.objects.filter(id=fitting_id).update(
                fitting_image_status=FittingImage.Status.FAILED
            )
            
            # 지수 백오프로 재시도 (60초 * 2^retry_count)
            countdown = 60 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)