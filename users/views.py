from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .serializers import UserOnboardingSerializer, UserProfileSerializer


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
                serializer.data,
                status=status.HTTP_200_OK
            )


class UserMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """사용자 정보 조회"""
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

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
