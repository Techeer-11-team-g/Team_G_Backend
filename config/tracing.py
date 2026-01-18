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

        # Create resource with service name
        resource = Resource.create({
            "service.name": service_name,
            "service.version": "1.0.0",
        })

        # Configure Jaeger exporter - use UDP agent with small batch size
        jaeger_host = os.getenv('JAEGER_HOST', 'localhost')
        jaeger_port = int(os.getenv('JAEGER_PORT', '6831'))

        jaeger_exporter = JaegerExporter(
            agent_host_name=jaeger_host,
            agent_port=jaeger_port,
        )

        # Set up TracerProvider with BatchSpanProcessor
        # Use small batch size to avoid UDP "Message too long" errors
        provider = TracerProvider(resource=resource)
        span_processor = BatchSpanProcessor(
            jaeger_exporter,
            max_export_batch_size=10,  # Small batches for UDP size limit
            schedule_delay_millis=1000,  # Export every 1 second
        )
        provider.add_span_processor(span_processor)
        trace.set_tracer_provider(provider)

        # Auto-instrumentation for Django
        DjangoInstrumentor().instrument()

        # Auto-instrumentation for Celery
        CeleryInstrumentor().instrument()

        # Auto-instrumentation for requests library (external API calls)
        RequestsInstrumentor().instrument()

        # Auto-instrumentation for httpx (used by Anthropic SDK)
        HTTPXClientInstrumentor().instrument()

        # Auto-instrumentation for gRPC (used by Google Cloud Vision/Storage)
        GrpcInstrumentorClient().instrument()

        # Add trace_id to logs
        LoggingInstrumentor().instrument(set_logging_format=True)

        _tracing_initialized = True
        logger.info(f"OpenTelemetry tracing initialized: Jaeger UDP agent at {jaeger_host}:{jaeger_port}")

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
