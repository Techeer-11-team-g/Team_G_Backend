from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import UserOnboardingView, UserMeView, UserRegisterView

urlpatterns = [
    # 인증 API
    path("auth/register", UserRegisterView.as_view()),
    path("auth/login", TokenObtainPairView.as_view()),
    path("auth/refresh", TokenRefreshView.as_view()),

    # 사용자 API
    path("users/profile", UserMeView.as_view()),
    path("users/onboarding", UserOnboardingView.as_view()),
]
