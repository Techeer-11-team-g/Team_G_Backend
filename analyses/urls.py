from django.urls import path
from .views import UploadedImageView, ImageAnalysisView

app_name = 'analyses'

urlpatterns = [
    # 이미지 업로드
    path('api/v1/uploaded-images', UploadedImageView.as_view(), name='uploaded-image-list-create'),

    # 이미지 분석
    path('api/v1/analyses', ImageAnalysisView.as_view(), name='analysis-create'),
]
