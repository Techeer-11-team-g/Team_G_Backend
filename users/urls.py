from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import UserOnboardingView, UserMeView, UserRegisterView, GoogleLoginView

urlpatterns = [
    # 인증 API
    path("auth/register", UserRegisterView.as_view()),
    path("auth/login", TokenObtainPairView.as_view()),
    path("auth/refresh", TokenRefreshView.as_view()),
    path("auth/google", GoogleLoginView.as_view()),  # 구글 소셜 로그인

    # 사용자 API
    path("users/profile", UserMeView.as_view()),
    path("users/onboarding", UserOnboardingView.as_view()),
]
