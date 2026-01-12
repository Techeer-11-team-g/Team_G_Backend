from django.urls import path
from .views import UserOnboardingView

urlpatterns = [
    path("me/onboarding", UserOnboardingView.as_view()),
]