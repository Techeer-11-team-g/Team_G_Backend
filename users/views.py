from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .serializers import UserOnboardingSerializer


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
            )s