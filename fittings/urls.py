from django.urls import path
from .views import (
    UserImageUploadView,
    FittingRequestView, 
    FittingStatusView, 
    FittingResultView
)

urlpatterns = [
    # 사용자 전신 이미지 업로드
    path('user-images', UserImageUploadView.as_view(), name='user-image-upload'),
    
    # 가상 피팅
    path('fitting-images', FittingRequestView.as_view(), name='fitting-request'),
    path('fitting-images/<int:fitting_image_id>/status', FittingStatusView.as_view(), name='fitting-status'),
    path('fitting-images/<int:fitting_image_id>', FittingResultView.as_view(), name='fitting-result'),
]