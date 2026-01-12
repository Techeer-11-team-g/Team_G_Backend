from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import FittingImage
from .serializers import FittingImageSerializer, FittingStatusSerializer
from .tasks import process_fitting_task

class FittingRequestView(APIView):
    """
    [POST] 가상 피팅 요청 생성
    """
    def post(self, request):
        # 명세서의 Request Body 반영: detected_object_id, product_id, user_image_url
        product_id = request.data.get('product_id')
        user_image_url = request.data.get('user_image_url')
        user_image_id = request.data.get('user_image_id')
        
        # 1. DB 레코드 생성 (ERD의 fitting_image 테이블 기반)
        fitting = FittingImage.objects.create(
            product_id=product_id,
            user_image_id=user_image_id,
            fitting_image_status=FittingImage.Status.PENDING
        )

        # 2. Celery 비동기 작업 시작
        process_fitting_task.delay(fitting.id)

        serializer = FittingImageSerializer(fitting)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

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