from django.urls import path
from .views import UploadedImageView

app_name = 'analyses'

urlpatterns = [
    path('api/v1/uploaded-images', UploadedImageView.as_view(), name='uploaded-image-list-create'),
]
