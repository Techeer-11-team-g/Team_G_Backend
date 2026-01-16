"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView


def health_check(request):
    """Health check endpoint."""
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health_check'),
    path('', include('django_prometheus.urls')),  # /metrics endpoint
    path('api/v1/users/', include('users.urls')), # 명세서의 /api/v1/users/ 규격을 맞추기 위해 'users/'를 경로에 추가
    path('api/v1/orders/', include('orders.urls')),
    path('api/v1/analyses/', include('analyses.urls')),
    path('api/v1/fittings/', include('fittings.urls')),

    # 스웨거 및 API 문서 설정 
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
