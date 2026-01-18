from django.apps import AppConfig


class AnalysesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analyses'
    verbose_name = 'Image Analyses'

    def ready(self):
        """Initialize OpenTelemetry tracing when Django starts."""
        try:
            from config.tracing import init_tracing
            init_tracing(service_name="team-g-backend")
        except ImportError:
            pass  # Tracing packages not installed
