from django.urls import path
from .views import UserOnboardingView

urlpatterns = [
    
    path("users/me", UserMeView.as_view()),
    path("users/onboarding", UserOnboardingView.as_view()),
]
