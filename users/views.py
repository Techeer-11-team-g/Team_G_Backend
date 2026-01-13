from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status


from .serializers import (
    UserOnboardingSerializer, 
    UserProfileSerializer, 
    UserUpdateSerializer
)


class UserOnboardingView(APIView):
    permission_classes = [IsAuthenticated]

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
                {"message": "사용자 필수 정보(온보딩)가 성공적으로 저장되었습니다."},
                status=status.HTTP_200_OK
            )

class UserMeView(APIView):
    # 로그인한 사용자만 접근 가능하도록 설정
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """현재 로그인한 본인의 정보 조회"""
        # request.user에는 현재 로그인된 사용자의 객체가 담겨 있습니다.
        # 기존 Serializer 유지 (UserUpdateSerializer와 필드명이 다름에 주의)
        
        
    
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        """사용자 정보 수정"""
        serializer = UserUpdateSerializer(
            instance=request.user,
            data=request.data,
            partial=True
        )
        if serializer.is_valid(raise_exception=True):
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
