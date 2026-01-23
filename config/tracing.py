"""
OpenTelemetry tracing configuration for Team G Backend.

Initializes distributed tracing with Jaeger exporter and auto-instrumentation
for Django, Celery, and HTTP requests.

Usage:
    from config.tracing import init_tracing
    init_tracing()
"""

import os
import logging

logger = logging.getLogger(__name__)

# Flag to prevent double initialization
_tracing_initialized = False


def init_tracing(service_name: str = "team-g-backend"):
    """
    Initialize OpenTelemetry tracing with Jaeger exporter.

    This function should be called once at application startup:
    - In wsgi.py for Django web server
    - In celery.py for Celery workers

    Args:
        service_name: Name of the service for tracing identification
    """
    global _tracing_initialized

    if _tracing_initialized:
        logger.debug("Tracing already initialized, skipping")
        return

    # Check if tracing is enabled
    tracing_enabled = os.getenv('TRACING_ENABLED', 'true').lower() == 'true'
    if not tracing_enabled:
        logger.info("Tracing is disabled via TRACING_ENABLED=false")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.propagators.composite import CompositePropagator
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        from opentelemetry.baggage.propagation import W3CBaggagePropagator

        # Create resource with service name
        resource = Resource.create({
            "service.name": service_name,
            "service.version": "1.0.0",
        })

        # Configure Jaeger exporter - use HTTP collector (no size limit)
        jaeger_host = os.getenv('JAEGER_HOST', 'localhost')
        jaeger_collector_port = int(os.getenv('JAEGER_COLLECTOR_PORT', '14268'))

        jaeger_exporter = JaegerExporter(
            collector_endpoint=f'http://{jaeger_host}:{jaeger_collector_port}/api/traces',
        )

        # Set up TracerProvider with BatchSpanProcessor for efficient export
        provider = TracerProvider(resource=resource)

        # Add Jaeger exporter with batch processor
        jaeger_processor = BatchSpanProcessor(jaeger_exporter)
        provider.add_span_processor(jaeger_processor)

        trace.set_tracer_provider(provider)

        # Set up W3C TraceContext propagator for trace context propagation
        # This is required for inject() to work properly
        propagator = CompositePropagator([
            TraceContextTextMapPropagator(),
            W3CBaggagePropagator(),
        ])
        set_global_textmap(propagator)

        # Auto-instrumentation for Django
        DjangoInstrumentor().instrument()

        # Auto-instrumentation for Celery with explicit propagation
        # propagate_headers=True ensures trace context is passed to child tasks
        CeleryInstrumentor().instrument(propagate_headers=True)

        # Auto-instrumentation for requests library (external API calls)
        RequestsInstrumentor().instrument()

        # Auto-instrumentation for httpx (used by Anthropic SDK)
        HTTPXClientInstrumentor().instrument()

        # Auto-instrumentation for gRPC (used by Google Cloud Vision/Storage)
        GrpcInstrumentorClient().instrument()

        # Add trace_id to logs
        LoggingInstrumentor().instrument(set_logging_format=True)

        _tracing_initialized = True
        logger.info(f"OpenTelemetry tracing initialized: Jaeger HTTP collector at {jaeger_host}:{jaeger_collector_port}")

    except ImportError as e:
        logger.warning(f"OpenTelemetry packages not installed, tracing disabled: {e}")
    except Exception as e:
        logger.error(f"Failed to initialize tracing: {e}")


def get_current_trace_id() -> str:
    """
    Get the current trace ID for correlation with logs.

    Returns:
        Trace ID as hex string, or empty string if not available
    """
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span:
            trace_id = span.get_span_context().trace_id
            if trace_id:
                return format(trace_id, '032x')
    except Exception:
        pass
    return ""


# =============================================================================
# Tracing Decorators - 기존 create_span 패턴을 데코레이터로 제공
# =============================================================================

def traced(span_name: str = None, attributes: dict = None):
    """
    트레이싱 데코레이터.

    함수 실행을 자동으로 span으로 감싸고 예외를 기록합니다.
    기존 코드의 create_span 패턴을 대체할 수 있습니다.

    Args:
        span_name: span 이름 (기본값: module.function_name)
        attributes: span에 추가할 속성 (key: 속성명, value: 인자 인덱스 또는 키워드 이름)

    Usage:
        @traced("my_operation", attributes={"user_id": 0, "item_id": "item_id"})
        def my_function(user_id, item_id=None):
            ...

    Note:
        기존 create_span을 사용하는 코드는 그대로 유지됩니다.
        새 코드 작성 시 이 데코레이터 사용을 권장합니다.
    """
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                from opentelemetry import trace
                from opentelemetry.trace import StatusCode
            except ImportError:
                # OpenTelemetry가 없으면 그냥 실행
                return func(*args, **kwargs)

            tracer = trace.get_tracer(func.__module__)
            name = span_name or f"{func.__module__}.{func.__name__}"

            with tracer.start_as_current_span(name) as span:
                # 속성 추가
                if attributes:
                    for attr_name, arg_ref in attributes.items():
                        try:
                            if isinstance(arg_ref, int) and arg_ref < len(args):
                                span.set_attribute(attr_name, str(args[arg_ref]))
                            elif isinstance(arg_ref, str) and arg_ref in kwargs:
                                span.set_attribute(attr_name, str(kwargs[arg_ref]))
                        except Exception:
                            pass

                try:
                    result = func(*args, **kwargs)
                    span.set_status(StatusCode.OK)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(StatusCode.ERROR, str(e))
                    raise

        return wrapper
    return decorator


def traced_async(span_name: str = None, attributes: dict = None):
    """
    비동기 함수용 트레이싱 데코레이터.

    Args:
        span_name: span 이름 (기본값: module.function_name)
        attributes: span에 추가할 속성

    Usage:
        @traced_async("async_operation")
        async def my_async_function():
            ...
    """
    from functools import wraps

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                from opentelemetry import trace
                from opentelemetry.trace import StatusCode
            except ImportError:
                return await func(*args, **kwargs)

            tracer = trace.get_tracer(func.__module__)
            name = span_name or f"{func.__module__}.{func.__name__}"

            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for attr_name, arg_ref in attributes.items():
                        try:
                            if isinstance(arg_ref, int) and arg_ref < len(args):
                                span.set_attribute(attr_name, str(args[arg_ref]))
                            elif isinstance(arg_ref, str) and arg_ref in kwargs:
                                span.set_attribute(attr_name, str(kwargs[arg_ref]))
                        except Exception:
                            pass

                try:
                    result = await func(*args, **kwargs)
                    span.set_status(StatusCode.OK)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(StatusCode.ERROR, str(e))
                    raise

        return wrapper
    return decorator


def get_tracer(name: str = __name__):
    """
    트레이서 인스턴스 반환.

    Args:
        name: 트레이서 이름 (보통 모듈명)

    Returns:
        OpenTelemetry Tracer 또는 NoOp tracer
    """
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        # NoOp tracer 반환
        return _NoOpTracer()


class _NoOpTracer:
    """OpenTelemetry가 없을 때 사용하는 NoOp tracer."""

    def start_as_current_span(self, name, **kwargs):
        return _NoOpSpan()


class _NoOpSpan:
    """NoOp span (컨텍스트 매니저용)."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def set_attribute(self, key, value):
        pass

    def set_status(self, status, description=None):
        pass

    def record_exception(self, exception):
        pass
