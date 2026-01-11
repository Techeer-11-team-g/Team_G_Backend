"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.conf import settings
from django.conf.urls.static import static


def health_check(request):
    """Health check endpoint."""
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health_check'),
    path('', include('django_prometheus.urls')),  # /metrics endpoint
    path('', include('analyses.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
