from django.urls import path
from .views import (
    UserImageUploadView,
    FittingRequestView, 
    FittingStatusView, 
    FittingResultView,
    FittingByProductView
)

urlpatterns = [
    # 사용자 전신 이미지 업로드
    path('user-images', UserImageUploadView.as_view(), name='user-image-upload'),
    
    # 가상 피팅
    path('fitting-images', FittingRequestView.as_view(), name='fitting-request'),
    path('fitting-images/<int:fitting_image_id>/status', FittingStatusView.as_view(), name='fitting-status'),
    path('fitting-images/<int:fitting_image_id>', FittingResultView.as_view(), name='fitting-result'),
    
    # 상품별 피팅 결과 조회 (FITTING 버튼 클릭 시)
    path('products/<int:product_id>/fitting', FittingByProductView.as_view(), name='fitting-by-product'),
]