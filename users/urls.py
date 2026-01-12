from django.urls import path
from .views import UserOnboardingView, UserMeView

urlpatterns = [
    path("me", UserMeView.as_view()),
    path("onboarding", UserOnboardingView.as_view()),
]
