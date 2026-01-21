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
import psutil
from contextlib import contextmanager
from prometheus_client import Counter, Histogram, Gauge, push_to_gateway, REGISTRY

logger = logging.getLogger(__name__)


# =============================================================================
# Process/System Metrics (커스텀 구현)
# =============================================================================

PROCESS_CPU_PERCENT = Gauge(
    'teamg_process_cpu_percent',
    'CPU usage percentage of the Django process'
)

PROCESS_MEMORY_BYTES = Gauge(
    'teamg_process_memory_bytes',
    'Memory usage in bytes of the Django process',
    ['type']  # rss, vms
)

PROCESS_OPEN_FDS = Gauge(
    'teamg_process_open_fds',
    'Number of open file descriptors'
)

SYSTEM_CPU_PERCENT = Gauge(
    'teamg_system_cpu_percent',
    'System-wide CPU usage percentage'
)

SYSTEM_MEMORY_PERCENT = Gauge(
    'teamg_system_memory_percent',
    'System-wide memory usage percentage'
)

SYSTEM_MEMORY_BYTES = Gauge(
    'teamg_system_memory_bytes',
    'System memory in bytes',
    ['type']  # total, available, used
)


# 프로세스 객체를 캐싱하여 cpu_percent()가 정확한 값을 반환하도록 함
_cached_process = None


def update_process_metrics():
    """프로세스 및 시스템 메트릭 업데이트"""
    global _cached_process
    try:
        # 프로세스 객체 캐싱 (cpu_percent는 이전 호출과의 차이로 계산)
        if _cached_process is None:
            _cached_process = psutil.Process()
            _cached_process.cpu_percent()  # 첫 호출로 초기화

        # 현재 프로세스 메트릭
        PROCESS_CPU_PERCENT.set(_cached_process.cpu_percent())
        mem_info = _cached_process.memory_info()
        PROCESS_MEMORY_BYTES.labels(type='rss').set(mem_info.rss)
        PROCESS_MEMORY_BYTES.labels(type='vms').set(mem_info.vms)

        try:
            PROCESS_OPEN_FDS.set(_cached_process.num_fds())
        except (AttributeError, psutil.Error):
            pass  # Windows에서는 num_fds() 미지원

        # 시스템 전체 메트릭
        SYSTEM_CPU_PERCENT.set(psutil.cpu_percent())
        mem = psutil.virtual_memory()
        SYSTEM_MEMORY_PERCENT.set(mem.percent)
        SYSTEM_MEMORY_BYTES.labels(type='total').set(mem.total)
        SYSTEM_MEMORY_BYTES.labels(type='available').set(mem.available)
        SYSTEM_MEMORY_BYTES.labels(type='used').set(mem.used)
    except Exception as e:
        logger.warning(f"Failed to update process metrics: {e}")

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
# Chat/Agent Metrics
# =============================================================================

CHAT_MESSAGES_TOTAL = Counter(
    'teamg_chat_messages_total',
    'Total chat messages processed',
    ['status']  # success, error
)

CHAT_INTENT_TOTAL = Counter(
    'teamg_chat_intent_total',
    'Chat intent classification counts',
    ['intent', 'sub_intent']  # search/new_search, fitting/single_fit, commerce/add_cart
)

CHAT_AGENT_ROUTING_TOTAL = Counter(
    'teamg_chat_agent_routing_total',
    'Agent routing counts',
    ['agent']  # search_agent, fitting_agent, commerce_agent
)

CHAT_SESSION_OPERATIONS_TOTAL = Counter(
    'teamg_chat_session_operations_total',
    'Session management operations',
    ['operation']  # create, load, save, delete
)

CHAT_RESPONSE_DURATION = Histogram(
    'teamg_chat_response_duration_seconds',
    'Time to generate chat response',
    ['intent'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
)


# =============================================================================
# HTTP API Metrics
# =============================================================================

HTTP_REQUEST_DURATION = Histogram(
    'teamg_http_request_duration_seconds',
    'HTTP request duration by endpoint and method',
    ['method', 'endpoint', 'status_code'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

HTTP_REQUESTS_TOTAL = Counter(
    'teamg_http_requests_total',
    'Total HTTP requests by endpoint and status',
    ['method', 'endpoint', 'status_code']
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
