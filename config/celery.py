"""
Celery configuration for config project.
"""

import os
from celery import Celery
from celery.signals import worker_process_init, celeryd_init
from kombu import Queue

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Load config from Django settings, using CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# 큐 설정: 분석과 피팅을 분리
app.conf.task_queues = (
    Queue('default'),
    Queue('analysis'),  # 이미지 분석 전용
    Queue('fitting'),   # 가상 피팅 전용
)
app.conf.task_default_queue = 'default'

# 태스크별 큐 라우팅
app.conf.task_routes = {
    'analyses.tasks.*': {'queue': 'analysis'},
    'fittings.tasks.*': {'queue': 'fitting'},
}

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()


@worker_process_init.connect
def init_worker_tracing_prefork(**kwargs):
    """Initialize OpenTelemetry tracing for prefork pool workers."""
    try:
        from config.tracing import init_tracing
        init_tracing(service_name="team-g-celery-worker")
    except ImportError:
        pass  # Tracing packages not installed


@celeryd_init.connect
def init_worker_tracing_threads(**kwargs):
    """Initialize OpenTelemetry tracing for threads/solo pool (main process)."""
    try:
        from config.tracing import init_tracing
        init_tracing(service_name="team-g-celery-worker")
    except ImportError:
        pass  # Tracing packages not installed


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing Celery."""
    print(f'Request: {self.request!r}')
