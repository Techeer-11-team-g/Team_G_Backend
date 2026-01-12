from django.urls import path
from .views import UserOnboardingView

urlpatterns = [
    path("/onboarding", UserOnboardingView.as_view()),
]
