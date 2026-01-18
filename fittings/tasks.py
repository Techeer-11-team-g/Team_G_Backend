import logging
from contextlib import nullcontext
from celery import shared_task
from .models import FittingImage
from services.fashn_service import get_fashn_service
from services.metrics import (
    FITTINGS_REQUESTED_TOTAL,
    FITTING_DURATION,
    record_api_call,
    push_metrics,
)

logger = logging.getLogger(__name__)


def _get_tracer():
    """Get tracer lazily to ensure TracerProvider is initialized."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("fittings.tasks")
    except ImportError:
        return None


def _create_span(name: str):
    """Create a span if tracer is available, otherwise return nullcontext."""
    tracer = _get_tracer()
    if tracer:
        return tracer.start_as_current_span(name)
    return nullcontext()

@shared_task(bind=True, max_retries=3)
def process_fitting_task(self, fitting_id):
    """Process virtual fitting request with tracing and metrics."""
    with _create_span("process_fitting_task") as span:
        if span and hasattr(span, 'set_attribute'):
            span.set_attribute("fitting.id", fitting_id)

        try:
            # 1. Load fitting data
            with _create_span("1_load_fitting_data"):
                fitting = FittingImage.objects.select_related('user_image', 'product').get(id=fitting_id)
                fitting.fitting_image_status = FittingImage.Status.RUNNING
                fitting.save(update_fields=['fitting_image_status', 'updated_at'])

            # 2. Prepare fitting parameters
            with _create_span("2_prepare_fitting") as prep_span:
                service = get_fashn_service()
                category = service.map_category(fitting.product.category)
                if prep_span and hasattr(prep_span, 'set_attribute'):
                    prep_span.set_attribute("fitting.category", category)
                    prep_span.set_attribute("fitting.product_id", fitting.product.id)

            logger.info(f"Fitting {fitting_id}: category={fitting.product.category} -> {category}")

            # 3. Call The New Black API (with duration metric)
            with _create_span("3_call_thenewblack_api") as api_span:
                with record_api_call('thenewblack'):
                    with FITTING_DURATION.labels(category=category).time():
                        result = service.create_fitting_with_files(
                            model_image=fitting.user_image.user_image_url,
                            garment_image=fitting.product.product_image_url,
                            category=category
                        )
                if api_span and hasattr(api_span, 'set_attribute'):
                    api_span.set_attribute("api.status", result.status)

            # 4. Save result
            with _create_span("4_save_fitting_result"):
                if result.status == 'completed' and result.output_url:
                    fitting.fitting_image_status = FittingImage.Status.DONE
                    fitting.fitting_image_url = result.output_url
                    FITTINGS_REQUESTED_TOTAL.labels(status='success').inc()
                    logger.info(f"Fitting {fitting_id}: completed - {result.output_url[:60]}...")
                else:
                    fitting.fitting_image_status = FittingImage.Status.FAILED
                    FITTINGS_REQUESTED_TOTAL.labels(status='failed').inc()
                    logger.error(f"Fitting {fitting_id}: failed - {result.error}")

                fitting.save(update_fields=['fitting_image_status', 'fitting_image_url', 'updated_at'])

            # Push metrics to Pushgateway
            push_metrics()

        except Exception as exc:
            logger.exception(f"Fitting {fitting_id}: exception occurred")
            FITTINGS_REQUESTED_TOTAL.labels(status='error').inc()
            push_metrics()
            FittingImage.objects.filter(id=fitting_id).update(fitting_image_status=FittingImage.Status.FAILED)
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))  # Exponential backoff