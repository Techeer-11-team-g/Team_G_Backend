"""
users/views.py - 사용자 관련 API Views

이 모듈은 사용자 인증 및 프로필 관리 REST API 엔드포인트를 정의합니다.

API Endpoints:
    - POST  /api/v1/auth/register   : 회원가입
    - PATCH /api/v1/users/onboarding: 온보딩 정보 등록
    - GET   /api/v1/users/profile   : 프로필 조회
    - PATCH /api/v1/users/profile   : 프로필 수정

Note:
    - 회원가입을 제외한 모든 API는 JWT 인증이 필요합니다.
    - 로그인/토큰 갱신은 SimpleJWT 기본 뷰를 사용합니다.
"""

import logging
from contextlib import nullcontext

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from services.metrics import USERS_REGISTERED_TOTAL
from .serializers import (
    UserOnboardingSerializer,
    UserProfileSerializer,
    UserRegisterResponseSerializer,
    UserRegisterSerializer,
)

logger = logging.getLogger(__name__)


# =============================================================================
# OpenTelemetry 트레이싱 유틸리티
# =============================================================================

def _get_tracer():
    """
    OpenTelemetry Tracer를 지연 로딩합니다.
    
    Returns:
        Tracer | None: TracerProvider가 초기화된 경우 Tracer, 아니면 None
    """
    try:
        from opentelemetry import trace
        return trace.get_tracer("users.views")
    except ImportError:
        return None


def _create_span(name: str):
    """
    트레이싱 span을 생성합니다.
    
    Args:
        name: span 이름
        
    Returns:
        Span | nullcontext: Tracer가 있으면 Span, 없으면 nullcontext
    """
    tracer = _get_tracer()
    if tracer:
        return tracer.start_as_current_span(name)
    return nullcontext()


def _set_span_attr(span, key: str, value):
    """
    span에 attribute를 안전하게 설정합니다.
    
    Args:
        span: OpenTelemetry Span 객체
        key: attribute 키
        value: attribute 값
    """
    if span and hasattr(span, 'set_attribute'):
        span.set_attribute(key, value)


# =============================================================================
# API Views
# =============================================================================

class UserRegisterView(APIView):
    """
    회원가입 API
    
    Endpoint: POST /api/v1/auth/register
    
    기능:
        - 신규 사용자 계정 생성
        - JWT 토큰 발급 (access, refresh)
    
    Authentication:
        인증 불필요 (AllowAny)
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Users"],
        summary="회원가입",
        description="신규 사용자를 등록하고 인증 토큰을 발급합니다.",
        request=UserRegisterSerializer,
        responses={201: UserRegisterResponseSerializer}
    )
    def post(self, request):
        """신규 사용자를 등록합니다."""
        with _create_span("api_user_register") as span:
            _set_span_attr(span, "http.method", "POST")
            _set_span_attr(span, "api.endpoint", "/api/v1/auth/register")

            # Step 1: 입력 검증
            with _create_span("1_validate_register_input") as v_span:
                serializer = UserRegisterSerializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                _set_span_attr(v_span, "validation", "passed")

            # Step 2: 사용자 생성
            with _create_span("2_create_user_db") as db_span:
                user = serializer.save()
                _set_span_attr(db_span, "user.id", user.id)
                _set_span_attr(db_span, "service", "mysql")

            # Step 3: JWT 토큰 생성
            with _create_span("3_generate_jwt_tokens") as token_span:
                refresh = RefreshToken.for_user(user)
                _set_span_attr(token_span, "token_type", "JWT")

            # 메트릭 수집 및 로깅
            USERS_REGISTERED_TOTAL.inc()
            logger.info(f"신규 사용자 등록: id={user.id}")

            _set_span_attr(span, "user.id", user.id)
            _set_span_attr(span, "status", "success")

            response_data = {
                'user': {
                    'user_id': user.id,
                    'username': user.username,
                    'email': user.email,
                },
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                }
            }
            return Response(response_data, status=status.HTTP_201_CREATED)


class UserOnboardingView(APIView):
    """
    온보딩 API
    
    Endpoint: PATCH /api/v1/users/onboarding
    
    기능:
        - 신규 가입 후 필수 정보 등록
        - 이메일, 주소, 결제 수단, 전화번호 업데이트
    
    Authentication:
        JWT 인증 필요
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Users"],
        summary="사용자 필수 정보 등록 (온보딩)",
        description="신규 사용자의 이메일, 주소, 결제 수단, 전화번호를 등록합니다.",
        request=UserOnboardingSerializer,
        responses={
            200: UserOnboardingSerializer,
            400: OpenApiResponse(description="Invalid request data"),
            401: OpenApiResponse(description="Unauthorized"),
        },
        examples=[
            OpenApiExample(
                "온보딩 요청 예시",
                value={
                    "user_email": "user@example.com",
                    "address": "서울시 강남구",
                    "payment": "card",
                    "phone_number": "010-1234-5678"
                },
                request_only=True,
            ),
        ]
    )
    def patch(self, request):
        """온보딩 정보를 등록합니다."""
        with _create_span("api_user_onboarding") as span:
            _set_span_attr(span, "user.id", request.user.id)

            # Step 1: 입력 검증
            with _create_span("1_validate_onboarding_input") as v_span:
                serializer = UserOnboardingSerializer(
                    instance=request.user,
                    data=request.data,
                    partial=True
                )
                serializer.is_valid(raise_exception=True)
                _set_span_attr(v_span, "validation", "passed")

            # Step 2: DB 업데이트
            with _create_span("2_update_user_db") as db_span:
                serializer.save()
                _set_span_attr(db_span, "user.id", request.user.id)
                _set_span_attr(db_span, "service", "mysql")

            logger.info(f"온보딩 완료: user_id={request.user.id}")
            return Response(serializer.data, status=status.HTTP_200_OK)


class UserMeView(APIView):
    """
    현재 사용자 프로필 API
    
    Endpoints:
        - GET /api/v1/users/profile: 프로필 조회
        - PATCH /api/v1/users/profile: 프로필 수정
    
    기능:
        - 로그인한 사용자의 프로필 정보 조회/수정
    
    Authentication:
        JWT 인증 필요
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Users"],
        summary="사용자 정보 조회",
        description="현재 로그인한 사용자의 프로필 정보를 조회합니다.",
        responses={200: UserProfileSerializer}
    )
    def get(self, request):
        """사용자 프로필을 조회합니다."""
        with _create_span("api_user_me_get") as span:
            _set_span_attr(span, "user.id", request.user.id)

            with _create_span("1_fetch_user_db") as db_span:
                serializer = UserProfileSerializer(request.user)
                _set_span_attr(db_span, "service", "mysql")

            return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Users"],
        summary="사용자 정보 수정",
        description="현재 로그인한 사용자의 프로필 정보를 수정합니다.",
        request=UserProfileSerializer,
        responses={200: UserProfileSerializer}
    )
    def patch(self, request):
        """사용자 프로필을 수정합니다."""
        with _create_span("api_user_me_patch") as span:
            _set_span_attr(span, "user.id", request.user.id)

            # Step 1: 입력 검증
            with _create_span("1_validate_profile_input") as v_span:
                serializer = UserProfileSerializer(
                    instance=request.user,
                    data=request.data,
                    partial=True
                )
                serializer.is_valid(raise_exception=True)
                _set_span_attr(v_span, "validation", "passed")

            # Step 2: DB 업데이트
            with _create_span("2_update_profile_db") as db_span:
                serializer.save()
                _set_span_attr(db_span, "service", "mysql")

            logger.info(f"프로필 수정: user_id={request.user.id}")
            return Response(serializer.data, status=status.HTTP_200_OK)
