from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from .models import FittingImage, UserImage
from .serializers import (
    FittingImageSerializer, 
    FittingStatusSerializer, 
    FittingResultSerializer,
    UserImageUploadSerializer
)
from .tasks import process_fitting_task


class UserImageUploadView(APIView):
    """
    [POST] 사용자 전신 이미지 업로드
    POST /api/v1/user-images
    
    파일을 업로드하면 URL로 변환하여 저장 후 반환
    """
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = UserImageUploadSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class FittingRequestView(APIView):
    """
    [POST] 가상 피팅 요청
    POST /api/v1/fitting-images
    """
    def post(self, request):
        serializer = FittingImageSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            fitting = serializer.save(fitting_image_status=FittingImage.Status.PENDING)
            process_fitting_task.delay(fitting.id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class FittingStatusView(APIView):
    """
    [GET] 가상 피팅 상태 조회
    GET /api/v1/fitting-images/{fitting_image_id}/status
    """
    def get(self, request, fitting_image_id):
        fitting = get_object_or_404(FittingImage, id=fitting_image_id)
        serializer = FittingStatusSerializer(fitting)
        return Response(serializer.data, status=status.HTTP_200_OK)


class FittingResultView(APIView):
    """
    [GET] 가상 피팅 결과 조회
    GET /api/v1/fitting-images/{fitting_image_id}
    """
    def get(self, request, fitting_image_id):
        fitting = get_object_or_404(FittingImage, id=fitting_image_id)
        serializer = FittingResultSerializer(fitting)
        return Response(serializer.data, status=status.HTTP_200_OK)


class FittingByProductView(APIView):
    """
    [GET] 상품 ID로 피팅 결과 조회
    GET /api/v1/products/{product_id}/fitting
    
    사용자가 FITTING 버튼을 클릭했을 때,
    해당 상품에 대해 미리 생성된 피팅 결과를 조회합니다.
    """
    def get(self, request, product_id):
        # 로그인한 사용자의 피팅 결과 조회
        user = request.user
        
        if not user.is_authenticated:
            return Response(
                {'error': '로그인이 필요합니다.'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # 해당 사용자 + 상품에 대한 피팅 결과 조회
        fitting = FittingImage.objects.filter(
            user_image__user=user,
            product_id=product_id,
            is_deleted=False
        ).order_by('-created_at').first()
        
        if not fitting:
            return Response(
                {'error': '해당 상품에 대한 피팅 결과가 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = FittingResultSerializer(fitting)
        return Response(serializer.data, status=status.HTTP_200_OK)