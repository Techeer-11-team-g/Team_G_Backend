"""
Custom Prometheus metrics for Team G image analysis pipeline.

Metrics are registered once as module-level singletons to prevent
duplicate registration errors when modules are reloaded.

Usage:
    from services.metrics import (
        ANALYSIS_TOTAL,
        ANALYSIS_DURATION,
        record_api_call,
    )

    # Counter
    ANALYSIS_TOTAL.labels(status='success').inc()

    # Histogram with context manager
    with ANALYSIS_DURATION.labels(stage='detect_objects').time():
        detect_objects(image)
"""

import os
import time
import logging
from contextlib import contextmanager
from prometheus_client import Counter, Histogram, Gauge, push_to_gateway, REGISTRY
from prometheus_client import ProcessCollector, PlatformCollector, REGISTRY as PROM_REGISTRY

logger = logging.getLogger(__name__)

# Process metrics collector 등록 (CPU, Memory 등)
# django-prometheus가 자동으로 등록하지 않으므로 명시적으로 추가
try:
    ProcessCollector(registry=PROM_REGISTRY)
    PlatformCollector(registry=PROM_REGISTRY)
    logger.info("Process and Platform collectors registered")
except ValueError:
    # Already registered
    pass

# Pushgateway 설정 (Celery 워커용)
PUSHGATEWAY_URL = os.getenv('PUSHGATEWAY_URL', 'localhost:9091')


# =============================================================================
# Analysis Pipeline Metrics
# =============================================================================

ANALYSIS_TOTAL = Counter(
    'teamg_analysis_total',
    'Total number of image analyses processed',
    ['status']  # success, failed
)

ANALYSIS_DURATION = Histogram(
    'teamg_analysis_duration_seconds',
    'Time spent in each analysis pipeline stage',
    ['stage'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0)
)

DETECTED_OBJECTS_TOTAL = Counter(
    'teamg_detected_objects_total',
    'Fashion items detected by category',
    ['category']
)

ANALYSIS_IN_PROGRESS = Gauge(
    'teamg_analysis_in_progress',
    'Number of analyses currently being processed'
)


# =============================================================================
# External API Metrics
# =============================================================================

EXTERNAL_API_REQUESTS = Counter(
    'teamg_external_api_requests_total',
    'External API calls by service and status',
    ['service', 'status']
)

EXTERNAL_API_DURATION = Histogram(
    'teamg_external_api_duration_seconds',
    'External API call latency by service',
    ['service'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
)

EXTERNAL_API_ERRORS = Counter(
    'teamg_external_api_errors_total',
    'External API errors by service and error type',
    ['service', 'error_type']
)


# =============================================================================
# Business Metrics
# =============================================================================

IMAGES_UPLOADED_TOTAL = Counter(
    'teamg_images_uploaded_total',
    'Total number of images uploaded'
)

ANALYSES_COMPLETED_TOTAL = Counter(
    'teamg_analyses_completed_total',
    'Total number of analyses completed successfully'
)

# =============================================================================
# User Metrics
# =============================================================================

USERS_REGISTERED_TOTAL = Counter(
    'teamg_users_registered_total',
    'Total number of user registrations'
)

USER_LOGINS_TOTAL = Counter(
    'teamg_user_logins_total',
    'Total number of user logins',
    ['status']  # success, failed
)

# =============================================================================
# Order Metrics
# =============================================================================

ORDERS_CREATED_TOTAL = Counter(
    'teamg_orders_created_total',
    'Total number of orders created'
)

CART_ITEMS_TOTAL = Counter(
    'teamg_cart_items_total',
    'Cart item operations',
    ['action']  # added, removed
)

FITTINGS_REQUESTED_TOTAL = Counter(
    'teamg_fittings_requested_total',
    'Virtual fitting requests by status',
    ['status']
)

FITTING_DURATION = Histogram(
    'teamg_fitting_duration_seconds',
    'Time spent processing virtual fitting requests',
    ['category'],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 90.0, 120.0, 180.0)
)

PRODUCT_MATCHES_TOTAL = Counter(
    'teamg_product_matches_total',
    'Products matched to detected objects',
    ['category']
)


# =============================================================================
# Helper Functions
# =============================================================================

def _classify_error(error: Exception) -> str:
    """Classify error type for metrics labeling."""
    error_str = str(error).lower()
    if 'timeout' in error_str:
        return 'timeout'
    elif 'rate limit' in error_str or '429' in error_str:
        return 'rate_limit'
    elif 'unauthorized' in error_str or '401' in error_str or '403' in error_str:
        return 'auth'
    elif '500' in error_str or '502' in error_str or '503' in error_str:
        return 'server_error'
    elif 'connection' in error_str:
        return 'connection'
    else:
        return 'unknown'


@contextmanager
def record_api_call(service: str):
    """
    Context manager to record external API call metrics.

    Usage:
        with record_api_call('google_vision'):
            response = vision_client.detect_objects(image)
    """
    start_time = time.time()
    try:
        yield
        EXTERNAL_API_REQUESTS.labels(service=service, status='success').inc()
    except Exception as e:
        EXTERNAL_API_REQUESTS.labels(service=service, status='error').inc()
        error_type = _classify_error(e)
        EXTERNAL_API_ERRORS.labels(service=service, error_type=error_type).inc()
        raise
    finally:
        duration = time.time() - start_time
        EXTERNAL_API_DURATION.labels(service=service).observe(duration)


def push_metrics(job_name: str = 'celery_worker'):
    """
    Celery 워커에서 Pushgateway로 메트릭 푸시.

    Usage:
        from services.metrics import push_metrics
        # 태스크 완료 후 호출
        push_metrics()
    """
    try:
        push_to_gateway(PUSHGATEWAY_URL, job=job_name, registry=REGISTRY)
        logger.debug(f"Metrics pushed to {PUSHGATEWAY_URL}")
    except Exception as e:
        logger.warning(f"Failed to push metrics to Pushgateway: {e}")
