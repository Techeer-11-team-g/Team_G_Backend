import logging
from contextlib import nullcontext

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiResponse

from .serializers import UserOnboardingSerializer, UserProfileSerializer, UserRegisterSerializer
from services.metrics import USERS_REGISTERED_TOTAL

logger = logging.getLogger(__name__)


def _get_tracer():
    """Get tracer lazily to ensure TracerProvider is initialized."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("users.views")
    except ImportError:
        return None


def _create_span(name: str):
    """Create a span if tracer is available."""
    tracer = _get_tracer()
    if tracer:
        return tracer.start_as_current_span(name)
    return nullcontext()


class UserRegisterView(APIView):
    """회원가입 API"""
    permission_classes = [AllowAny]

    @extend_schema(tags=["Users"], summary="회원가입", description="신규 사용자를 등록하고 인증 토큰을 발급합니다.")
    def post(self, request):
        with _create_span("api_user_register") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("http.method", "POST")
                span.set_attribute("api.endpoint", "/api/v1/users/register")

            # Step 1: Validate input
            with _create_span("1_validate_register_input") as v_span:
                serializer = UserRegisterSerializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                if v_span and hasattr(v_span, 'set_attribute'):
                    v_span.set_attribute("validation", "passed")

            # Step 2: Create user in database
            with _create_span("2_create_user_db") as db_span:
                user = serializer.save()
                if db_span and hasattr(db_span, 'set_attribute'):
                    db_span.set_attribute("user.id", user.id)
                    db_span.set_attribute("service", "mysql")

            # Step 3: Generate JWT tokens
            with _create_span("3_generate_jwt_tokens") as token_span:
                refresh = RefreshToken.for_user(user)
                if token_span and hasattr(token_span, 'set_attribute'):
                    token_span.set_attribute("token_type", "JWT")

            USERS_REGISTERED_TOTAL.inc()
            logger.info(f"New user registered: {user.id}")

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", user.id)
                span.set_attribute("status", "success")

            return Response({
                'user': {
                    'user_id': user.id,
                    'username': user.username,
                    'email': user.email,
                },
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                }
            }, status=status.HTTP_201_CREATED)


class UserOnboardingView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Users"],
        summary="사용자 필수 정보 등록 (온보딩)",
        description="신규 사용자의 이메일, 주소, 결제 수단, 전화번호를 등록합니다.",
        request=UserOnboardingSerializer,
        responses={
            200: UserOnboardingSerializer,
            400: OpenApiResponse(description="Invalid request data (필수 필드 누락, 형식 오류 등)"),
            401: OpenApiResponse(description="Unauthorized (인증 토큰 유효하지 않음)"),
            500: OpenApiResponse(description="Internal server error (DB 저장 오류 등)"),
        },
        examples=[
            OpenApiExample(
                "온보딩 요청 예시",
                value={
                    "user_email": "string",
                    "address": "string",
                    "payment": "card",
                    "phone_number": "string"
                },
                request_only=True,
            ),
            OpenApiExample(
                "온보딩 성공 응답 예시",
                value={
                    "user_id": 1,
                    "user_name": "string",
                    "user_email": "string",
                    "address": "string",
                    "payment": "card",
                    "phone_number": "string",
                    "updated_at": "2026-01-10T12:34:56Z"
                },
                response_only=True,
            )
        ]
    )
    
    def patch(self, request):
        with _create_span("api_user_onboarding") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)

            # Step 1: Validate input
            with _create_span("1_validate_onboarding_input") as v_span:
                serializer = UserOnboardingSerializer(
                    instance=request.user,
                    data=request.data,
                    partial=True
                )
                serializer.is_valid(raise_exception=True)
                if v_span and hasattr(v_span, 'set_attribute'):
                    v_span.set_attribute("validation", "passed")

            # Step 2: Update user in database
            with _create_span("2_update_user_db") as db_span:
                serializer.save()
                if db_span and hasattr(db_span, 'set_attribute'):
                    db_span.set_attribute("user.id", request.user.id)
                    db_span.set_attribute("service", "mysql")

            logger.info(f"User onboarding updated: {request.user.id}")
            return Response(
                serializer.data,
                status=status.HTTP_200_OK
            )


class UserMeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Users"], summary="사용자 정보 조회", description="현재 로그인한 사용자의 프로필 정보를 조회합니다.")
    def get(self, request):
        """사용자 정보 조회"""
        with _create_span("api_user_me_get") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)

            # Step 1: Fetch user from database
            with _create_span("1_fetch_user_db") as db_span:
                serializer = UserProfileSerializer(request.user)
                if db_span and hasattr(db_span, 'set_attribute'):
                    db_span.set_attribute("service", "mysql")

            return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(tags=["Users"], summary="사용자 정보 수정", description="현재 로그인한 사용자의 프로필 정보를 수정합니다.")
    def patch(self, request):
        """사용자 정보 수정"""
        with _create_span("api_user_me_patch") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)

            # Step 1: Validate input
            with _create_span("1_validate_profile_input") as v_span:
                serializer = UserProfileSerializer(
                    instance=request.user,
                    data=request.data,
                    partial=True
                )
                serializer.is_valid(raise_exception=True)
                if v_span and hasattr(v_span, 'set_attribute'):
                    v_span.set_attribute("validation", "passed")

            # Step 2: Update user in database
            with _create_span("2_update_profile_db") as db_span:
                serializer.save()
                if db_span and hasattr(db_span, 'set_attribute'):
                    db_span.set_attribute("service", "mysql")

            logger.info(f"User profile updated: {request.user.id}")
            return Response(
                serializer.data,
                status=status.HTTP_200_OK
            )
