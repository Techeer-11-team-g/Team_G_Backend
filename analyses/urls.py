from django.urls import path
from .views import (
    UploadedImageView,
    UploadedImageHistoryView,
    ImageAnalysisView,
    ImageAnalysisStatusView,
    ImageAnalysisResultView,
    FeedView,
    MyHistoryView,
    TogglePublicView,
)

app_name = 'analyses'

urlpatterns = [
    # 이미지 업로드
    path('api/v1/uploaded-images', UploadedImageView.as_view(), name='uploaded-image-list-create'),

    # 통합 히스토리 조회 (API 10)
    path('api/v1/uploaded-images/<int:uploaded_image_id>', UploadedImageHistoryView.as_view(), name='uploaded-image-history'),

    # 공개/비공개 토글
    path('api/v1/uploaded-images/<int:uploaded_image_id>/visibility', TogglePublicView.as_view(), name='uploaded-image-visibility'),

    # 이미지 분석
    path('api/v1/analyses', ImageAnalysisView.as_view(), name='analysis-create'),
    path('api/v1/analyses/<int:analysis_id>/status', ImageAnalysisStatusView.as_view(), name='analysis-status'),
    path('api/v1/analyses/<int:analysis_id>', ImageAnalysisResultView.as_view(), name='analysis-result'),

    # 피드 & 히스토리
    path('api/v1/feed', FeedView.as_view(), name='feed'),
    path('api/v1/my-history', MyHistoryView.as_view(), name='my-history'),
]
