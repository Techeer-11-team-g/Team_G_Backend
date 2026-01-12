from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import FittingImage
from .tasks import process_fitting_task

class FittingRequestView(APIView):
    """
    [POST] 가상 피팅 요청 생성
    """
    def post(self, request):
        # 명세서의 Request Body 반영: detected_object_id, product_id, user_image_url
        product_id = request.data.get('product_id')
        user_image_url = request.data.get('user_image_url')
        
        # 1. DB 레코드 생성 (ERD의 fitting_image 테이블 기반)
        fitting = FittingImage.objects.create(
            product_id=product_id,
            # user_image_id는 명세서상 user_image_url을 받아 처리하므로 
            # 프로젝트 로직에 따라 URL 저장 혹은 ID 매핑 필요
            fitting_image_status=FittingImage.Status.PENDING
        )

        # 2. Celery 비동기 작업 시작
        process_fitting_task.delay(fitting.id)

        # 3. 명세서 규격에 맞는 Response (201 Created)
        return Response({
            "fitting_image_id": fitting.id,
            "status": "PENDING",
            "polling": {
                "status_url": f"/api/v1/fitting-images/{fitting.id}/status",
                "result_url": f"/api/v1/fitting-images/{fitting.id}"
            }
        }, status=status.HTTP_201_CREATED)

class FittingStatusView(APIView):
    """
    [GET] 가상 피팅 상태 조회
    """
    def get(self, request, fitting_image_id):
        fitting = get_object_or_404(FittingImage, id=fitting_image_id)
        
        # 명세서 반영: status, progress, updated_at
        return Response({
            "status": "RUNNING" if fitting.fitting_image_status == FittingImage.Status.RUNNING else fitting.fitting_image_status.upper(),
            "progress": 40 if fitting.fitting_image_status == FittingImage.Status.RUNNING else 100, # 예시 데이터
            "updated_at": fitting.updated_at.isoformat()
        }, status=status.HTTP_200_OK)

class FittingResultView(APIView):
    """
    [GET] 가상 피팅 결과 조회
    """
    def get(self, request, fitting_image_id):
        fitting = get_object_or_404(FittingImage, id=fitting_image_id)
        
        # 명세서 반영: fitting_image_id, status, fitting_image_url, completed_at
        return Response({
            "fitting_image_id": fitting.id,
            "status": "DONE" if fitting.fitting_image_status == FittingImage.Status.DONE else fitting.fitting_image_status.upper(),
            "fitting_image_url": fitting.fitting_image_url,
            "completed_at": fitting.updated_at.isoformat() if fitting.fitting_image_status == FittingImage.Status.DONE else None
        }, status=status.HTTP_200_OK)