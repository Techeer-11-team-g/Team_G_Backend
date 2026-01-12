from django.urls import path
from .views import FittingRequestView

urlpatterns = [
    path('request/', FittingRequestView.as_view(), name='fitting-request'),
]