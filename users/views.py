from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiResponse

from .serializers import UserOnboardingSerializer, UserProfileSerializer, UserRegisterSerializer


class UserRegisterView(APIView):
    """회원가입 API"""
    permission_classes = [AllowAny]

    @extend_schema(tags=["Users"], summary="회원가입", description="신규 사용자를 등록하고 인증 토큰을 발급합니다.")
    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
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
        # instance=request.user를 넘겨주면 '생성'이 아닌 '수정' 모드로 동작합니다.
        serializer = UserOnboardingSerializer(
            instance=request.user, 
            data=request.data, 
            partial=True
        )
        
        if serializer.is_valid(raise_exception=True):
            serializer.save() # serializer의 update() 메서드가 호출됨
            return Response(
                serializer.data,
                status=status.HTTP_200_OK
            )


class UserMeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Users"], summary="사용자 정보 조회", description="현재 로그인한 사용자의 프로필 정보를 조회합니다.")
    def get(self, request):
        """사용자 정보 조회"""
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(tags=["Users"], summary="사용자 정보 수정", description="현재 로그인한 사용자의 프로필 정보를 수정합니다.")
    def patch(self, request):
        """사용자 정보 수정"""
        # 수정 시에도 UserProfileSerializer를 사용할지, 별도 Serializer를 사용할지 결정 필요
        # 명세에 따라 UserProfileSerializer를 재사용하거나 필요한 경우 분리
        # 여기서는 조회와 동일한 필드를 반환하고, 수정은 partial=True로 처리
        serializer = UserProfileSerializer(
            instance=request.user,
            data=request.data,
            partial=True
        )
        
        if serializer.is_valid(raise_exception=True):
            serializer.save()
            return Response(
                serializer.data,
                status=status.HTTP_200_OK
            )
