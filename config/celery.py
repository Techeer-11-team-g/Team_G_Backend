"""
Celery configuration for config project.
"""

import os
from celery import Celery
from celery.signals import worker_process_init

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Load config from Django settings, using CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()


@worker_process_init.connect
def init_worker_tracing(**kwargs):
    """Initialize OpenTelemetry tracing when Celery worker starts."""
    try:
        from config.tracing import init_tracing
        init_tracing(service_name="team-g-celery-worker")
    except ImportError:
        pass  # Tracing packages not installed


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing Celery."""
    print(f'Request: {self.request!r}')
