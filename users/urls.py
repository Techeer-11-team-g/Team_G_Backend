from django.urls import path
from .views import UserOnboardingView, UserMeView

urlpatterns = [
    path("users/me", UserMeView.as_view()), 
    path("onboarding", UserOnboardingView.as_view()),
]
