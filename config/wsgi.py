"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialize OpenTelemetry tracing before Django starts
try:
    from config.tracing import init_tracing
    init_tracing(service_name="team-g-backend")
except ImportError:
    pass  # Tracing packages not installed

application = get_wsgi_application()
