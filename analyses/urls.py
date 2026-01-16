from django.urls import path
from .views import (
    UploadedImageView,
    UploadedImageHistoryView,
    ImageAnalysisView,
    ImageAnalysisStatusView,
    ImageAnalysisResultView,
)

app_name = 'analyses'

urlpatterns = [
    # 이미지 업로드
    path('api/v1/uploaded-images', UploadedImageView.as_view(), name='uploaded-image-list-create'),

    # 통합 히스토리 조회 (API 10)
    path('api/v1/uploaded-images/<int:uploaded_image_id>', UploadedImageHistoryView.as_view(), name='uploaded-image-history'),

    # 이미지 분석
    path('api/v1/analyses', ImageAnalysisView.as_view(), name='analysis-create'),
    path('api/v1/analyses/<int:analysis_id>/status', ImageAnalysisStatusView.as_view(), name='analysis-status'),
    path('api/v1/analyses/<int:analysis_id>', ImageAnalysisResultView.as_view(), name='analysis-result'),
]
