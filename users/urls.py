from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import UserOnboardingView, UserMeView, UserRegisterView, GoogleLoginView


# SimpleJWT 뷰에 Swagger 태그 및 설명 추가
DecoratedTokenObtainPairView = extend_schema_view(
    post=extend_schema(
        tags=["Users"],
        summary="로그인 (JWT 토큰 발급)",
        description="사용자 인증 후 JWT access/refresh 토큰을 발급합니다.",
    )
)(TokenObtainPairView)

DecoratedTokenRefreshView = extend_schema_view(
    post=extend_schema(
        tags=["Users"],
        summary="토큰 갱신",
        description="refresh 토큰으로 새로운 access 토큰을 발급받습니다.",
    )
)(TokenRefreshView)


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
