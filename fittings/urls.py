from django.urls import path
from .views import FittingRequestView, FittingStatusView, FittingResultView

urlpatterns = [
    path('fitting-images/', FittingRequestView.as_view(), name='fitting-request'),
    path('fitting-images/<int:fitting_image_id>/status/', FittingStatusView.as_view(), name='fitting-status'),
    path('fitting-images/<int:fitting_image_id>/', FittingResultView.as_view(), name='fitting-result'),
]