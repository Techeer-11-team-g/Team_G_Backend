from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import UserOnboardingView, UserMeView, UserRegisterView

urlpatterns = [
    # 현재 로그인한 본인의 정보 조회 
    path("me", UserMeView.as_view(), name="user-me"),

    # 사용자 필수 정보 등록(API 명세서 : /api/v1/users/onboarding)
    path("onboarding", UserOnboardingView.as_view(), name="user-onboarding"),
] 
