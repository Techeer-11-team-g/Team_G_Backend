from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiExample 

from .serializers import UserOnboardingSerializer, UserOnboardingResponseSerializer, UserProfileSerializer

class UserOnboardingView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="사용자 필수 정보 등록 (온보딩)",
        description="로그인한 사용자의 이메일, 주소, 결제수단, 전화번호를 등록하거나 수정합니다.",
        tags=['User']
        # Request Body 예시 
        request=UserOnboardingSerializer,
        examples=[
            OpenApiExample(
                'Valid Request',
                summary='요청 예시',
                description='명세서의 Request Body 양식입니다.',
                value={
                    "user_email": "user@example.com",
                    "address": "서울특별시 강남구 ...",
                    "payment": "card",
                    "phone_number": "010-1234-5678"
                },
                request_only=True
            )
        ],
        # Responses
        responses={
            200: UserOnboardingResponseSerializer, # 명세서 양식에 맞춘 응답
            400: OpenApiExample(
                'Bad Request',
                summary='400 error',
                description='필수 필드 누락, 이메일/전화번호 형식 오류',
                value={"message": "Invalid request data"}
            ),
            401: OpenApiExample(
                'Unauthorized',
                summary='401 error',
                description='인증 토큰이 없거나 유효하지 않음',
                value={"message": "Unauthorized"}
            ),
            500: OpenApiExample(
                'Internal Server Error',
                summary='500 error',
                description='데이터베이스 저장 중 오류 발생',
                value={"message": "Internal server error"}
            ),
        }
    )
    def patch(self, request):
        # instance=request.user를 넘겨주면 '생성'이 아닌 '수정' 모드로 동작합니다.
        serializer = UserOnboardingSerializer(
            instance=request.user, 
            data=request.data, 
            partial=True
        )
        
        # 중복 제거 및 들여쓰기 수정 
        if serializer.is_valid():
            serializer.save() # serializer의 update() 메서드가 호출됨
            return Response(
                UserOnboardingResponseSerializer(request.user).data, 
                status=status.HTTP_200_OK
            )
            
        # 400 에러 메시지 통일 ("message": "Invalid request data")
        return Response(
            {"message": "Invalid request data"}, 
            status=status.HTTP_400_BAD_REQUEST
        )

class UserMeView(APIView): 
    permission_classes = [IsAuthenticated] 
    @extend_schema(
        summary="현재 로그인한 본인의 정보 조회",
        description="로그인된 유저의 전체 프로필 정보를 조회합니다.",
        responses={200: UserProfileSerializer},
        tags=['User']
    )
    def get(self, request):
        """현재 로그인한 본인의 정보 조회"""
        serializer = UserProfileSerializer(request.user) 
        return Response(serializer.data, status=status.HTTP_200_OK) 
