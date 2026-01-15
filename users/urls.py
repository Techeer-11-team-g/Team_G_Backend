from django.urls import path
from .views import UserOnboardingView, UserMeView

urlpatterns = [
    path("users/profile", UserMeView.as_view()),
    path("users/onboarding", UserOnboardingView.as_view()),
]
