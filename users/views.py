from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

# 스웨거 설정을 위한 도구들
from drf_spectacular.utils import extend_schema, OpenApiExample
from .serializers import (
    UserOnboardingSerializer, 
    UserOnboardingResponseSerializer, # 새로 만든 응답용 시리얼라이저
    UserProfileSerializer
)

class UserOnboardingView(APIView):
    permission_classes = [IsAuthenticated]
    @extend_schema(
        summary="사용자 필수 정보 등록 (온보딩)",
        description="로그인한 사용자의 이메일, 주소, 결제수단, 전화번호를 등록하거나 수정합니다.",
        request=UserOnboardingSerializer,
        responses={
            200: UserOnboardingResponseSerializer, # 명세서 양식에 맞춘 응답
            400: OpenApiExample(
                'Bad Request',
                value={"message": "Invalid request data"},
                description="필수 필드 누락 또는 형식 오류"
            ),
            401: OpenApiExample(
                'Unauthorized',
                value={"message": "Unauthorized"},
                description="인증 토큰이 없거나 유효하지 않음"
            ),
            500: OpenApiExample(
                'Internal Server Error',
                value={"message": "Internal server error"},
                description="데이터베이스 저장 중 오류"
            ),
        },
        tags=['User']
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
            # 팀 명세서의 Response (200 OK) 양식에 맞춰 데이터를 반환합니다.
            response_serializer = UserOnboardingResponseSerializer(request.user)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        # 명세서에 정의된 400 에러 메시지 형식 준수
        return Response({"message": "Invalid request data"}, status=status.HTTP_400_BAD_REQUEST)


class UserMeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="현재 로그인한 본인의 정보 조회",
        description="로그인된 유저의 전체 프로필 정보를 조회합니다.",
        responses={200: UserProfileSerializer},
        tags=['User']
    )
    def get(self, request):
        """사용자 정보 조회"""
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)