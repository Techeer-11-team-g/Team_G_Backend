import os
from django.apps import AppConfig


class AnalysesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analyses'
    verbose_name = 'Image Analyses'

    def ready(self):
        """App initialization hook.

        Initialize OpenTelemetry tracing for Django (including runserver).
        This ensures trace context is propagated to Celery tasks.
        """
        # Celery worker에서는 celery.py에서 별도 초기화
        if os.environ.get('CELERY_WORKER', '').lower() == 'true':
            return

        # RUN_MAIN 체크: runserver의 auto-reloader에서 중복 실행 방지
        if os.environ.get('RUN_MAIN') != 'true':
            return

        try:
            from config.tracing import init_tracing
            init_tracing(service_name="team-g-backend")
        except ImportError:
            pass  # Tracing packages not installed
