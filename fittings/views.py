from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import FittingImage
from .serializers import FittingImageSerializer, FittingStatusSerializer
from .tasks import process_fitting_task

class FittingRequestView(APIView):
    def post(self, request):
        # 1. 시리얼라이저로 데이터 검증 (product, user_image 존재 여부 등 체크)
        serializer = FittingImageSerializer(data=request.data)
        
        if serializer.is_valid():
            # 2. DB 레코드 생성 (상태는 PENDING)
            fitting = serializer.save(fitting_image_status=FittingImage.Status.PENDING)
            
            # 3. Celery 태스크 실행 (fitting_id만 전달, 나머지는 DB에서 조회)
            process_fitting_task.delay(fitting.id)
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
class FittingStatusView(APIView):
    """
    [GET] 가상 피팅 상태 조회
    """
    def get(self, request, fitting_image_id):
        fitting = get_object_or_404(FittingImage, id=fitting_image_id)
        
        serializer = FittingStatusSerializer(fitting)
        return Response(serializer.data, status=status.HTTP_200_OK)

class FittingResultView(APIView):
    """
    [GET] 가상 피팅 결과 조회
    """
    def get(self, request, fitting_image_id):
        fitting = get_object_or_404(FittingImage, id=fitting_image_id)
        
        serializer = FittingImageSerializer(fitting)
        return Response(serializer.data, status=status.HTTP_200_OK)