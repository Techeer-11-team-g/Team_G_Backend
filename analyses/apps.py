from django.apps import AppConfig


class AnalysesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analyses'
    verbose_name = 'Image Analyses'

    def ready(self):
        """App initialization hook.

        Note: Tracing is initialized separately:
        - Django web server: config/wsgi.py
        - Celery worker: config/celery.py (via celeryd_init signal)
        """
        pass
