from django.urls import path
from .views import FittingRequestView, FittingStatusView, FittingResultView

urlpatterns = [
    # 가상 피팅 요청
    path('fitting-images', FittingRequestView.as_view(), name='fitting-request'),
    # 가상 피팅 상태 조회
    path('fitting-images/<int:fitting_image_id>/status', FittingStatusView.as_view(), name='fitting-status'),
    # 가상 피팅 결과 조회
    path('fitting-images/<int:fitting_image_id>', FittingResultView.as_view(), name='fitting-result'),
]