"""
fittings/views.py - 가상 피팅 API Views

이 모듈은 가상 피팅 관련 REST API 엔드포인트를 정의합니다.

API Endpoints:
    - POST /api/v1/user-images          : 사용자 전신 이미지 업로드
    - POST /api/v1/fitting-images       : 가상 피팅 요청
    - GET  /api/v1/fitting-images/{id}/status : 피팅 상태 조회
    - GET  /api/v1/fitting-images/{id}  : 피팅 결과 조회

Note:
    모든 API는 JWT 인증이 필요합니다.
"""

import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from analyses.utils import create_span
from .models import FittingImage
from .serializers import (
    FittingImageSerializer,
    FittingResultSerializer,
    FittingStatusSerializer,
    UserImageUploadSerializer,
)
from .tasks import process_fitting_task

logger = logging.getLogger(__name__)

# 트레이서 모듈명
TRACER_NAME = "fittings.views"


# =============================================================================
# API Views
# =============================================================================

class UserImageUploadView(APIView):
    """
    사용자 전신 이미지 업로드 API
    
    Endpoint: POST /api/v1/user-images
    
    기능:
        - 사용자 전신 이미지 업로드
        - 자동 이미지 최적화 (768x1024 리사이즈 + JPEG 압축)
        - GCS에 저장 후 URL 반환
    
    Authentication:
        JWT 인증 필요
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Fittings"],
        summary="사용자 전신 이미지 업로드",
        description="가상 피팅에 사용할 사용자 전신 이미지를 업로드합니다.",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'file': {
                        'type': 'string',
                        'format': 'binary',
                        'description': '업로드할 이미지 파일 (JPG, PNG, WEBP, 최대 10MB)'
                    }
                },
                'required': ['file']
            }
        },
        responses={201: UserImageUploadSerializer}
    )
    def post(self, request):
        """사용자 전신 이미지를 업로드합니다."""
        with create_span(TRACER_NAME, "api_user_image_upload") as span:
            span.set("user.id", request.user.id)

            serializer = UserImageUploadSerializer(
                data=request.data,
                context={'request': request}
            )

            if serializer.is_valid():
                user_image = serializer.save()
                logger.info(
                    "사용자 전신 이미지 업로드 완료",
                    extra={
                        'event': 'user_image_uploaded',
                        'user_id': request.user.id,
                        'user_image_id': user_image.id,
                    }
                )
                span.set("user_image.id", user_image.id)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class FittingRequestView(APIView):
    """
    가상 피팅 요청 API
    
    Endpoint: POST /api/v1/fitting-images
    
    기능:
        - 사용자 이미지 + 상품 조합으로 가상 피팅 요청
        - 동일 조합의 완료된 피팅이 있으면 캐싱된 결과 반환 (200 OK)
        - 신규 요청은 Celery 비동기 태스크로 처리 (201 Created)
        
    캐싱 전략:
        동일한 (user_image, product) 조합에 대해 완료된 피팅이 있으면
        API 호출 없이 기존 결과를 재사용합니다.
    
    Authentication:
        JWT 인증 필요
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Fittings"],
        summary="가상 피팅 요청",
        description="사용자 이미지와 상품 정보를 바탕으로 가상 피팅을 요청합니다. "
                    "동일한 조합의 결과가 이미 있으면 기존 결과를 반환합니다.",
        request=FittingImageSerializer,
        responses={
            201: FittingImageSerializer,
            200: FittingResultSerializer  # 캐싱된 결과 반환 시
        }
    )
    def post(self, request):
        """가상 피팅을 요청합니다."""
        with create_span(TRACER_NAME, "api_fitting_request") as span:
            span.set("user.id", request.user.id)

            serializer = FittingImageSerializer(
                data=request.data,
                context={'request': request}
            )

            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            user_image = serializer.validated_data.get('user_image_url')
            product = serializer.validated_data.get('product')

            # Step 1: 캐싱 확인 - 동일한 조합의 완료된 피팅이 있는지 확인
            existing_fitting = FittingImage.objects.filter(
                user_image=user_image,
                product=product,
                fitting_image_status=FittingImage.Status.DONE,
                is_deleted=False
            ).first()

            if existing_fitting:
                # 캐시 히트: 기존 결과 반환
                logger.info(
                    "가상 피팅 캐시 히트",
                    extra={
                        'event': 'fitting_cache_hit',
                        'user_id': request.user.id,
                        'fitting_id': existing_fitting.id,
                        'product_id': product.id,
                    }
                )
                span.set("fitting.cache_hit", True)
                span.set("fitting.id", existing_fitting.id)
                result_serializer = FittingResultSerializer(existing_fitting)
                return Response(result_serializer.data, status=status.HTTP_200_OK)

            # Step 2: 신규 피팅 생성
            fitting = serializer.save(fitting_image_status=FittingImage.Status.PENDING)

            # Step 3: Celery 비동기 태스크 실행
            from opentelemetry.propagate import inject
            headers = {}
            inject(headers)  # 트레이스 컨텍스트 전파
            process_fitting_task.apply_async(args=[fitting.id], headers=headers)

            logger.info(
                "가상 피팅 요청 생성",
                extra={
                    'event': 'fitting_requested',
                    'user_id': request.user.id,
                    'fitting_id': fitting.id,
                    'product_id': product.id,
                    'user_image_id': user_image.id,
                }
            )
            span.set("fitting.cache_hit", False)
            span.set("fitting.id", fitting.id)

            return Response(serializer.data, status=status.HTTP_201_CREATED)


class FittingStatusView(APIView):
    """
    가상 피팅 상태 조회 API
    
    Endpoint: GET /api/v1/fitting-images/{fitting_image_id}/status
    
    기능:
        - 피팅 작업의 현재 상태 조회
        - 클라이언트 폴링에 사용
    
    Response:
        - fitting_image_status: PENDING/RUNNING/DONE/FAILED
        - progress: 진행률 (0-100)
        - updated_at: 최종 업데이트 일시
    
    Authentication:
        JWT 인증 필요
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Fittings"],
        summary="가상 피팅 상태 조회",
        description="요청한 가상 피팅 작업의 현재 상태를 조회합니다.",
        responses={200: FittingStatusSerializer}
    )
    def get(self, request, fitting_image_id):
        """피팅 작업의 현재 상태를 조회합니다."""
        with create_span(TRACER_NAME, "api_fitting_status") as span:
            span.set("fitting.id", fitting_image_id)

            fitting = get_object_or_404(FittingImage, id=fitting_image_id)
            span.set("fitting.status", fitting.fitting_image_status)

            serializer = FittingStatusSerializer(fitting)
            return Response(serializer.data, status=status.HTTP_200_OK)


class FittingResultView(APIView):
    """
    가상 피팅 결과 조회 API
    
    Endpoint: GET /api/v1/fitting-images/{fitting_image_id}
    
    기능:
        - 완료된 피팅의 결과 이미지 URL 조회
        - 피팅 상태와 관계없이 조회 가능 (PENDING/RUNNING 상태도 조회 가능)
    
    Response:
        - fitting_image_id: 피팅 요청 ID
        - fitting_image_status: 피팅 상태
        - fitting_image_url: 결과 이미지 URL (완료 시에만 값 존재)
        - completed_at: 완료 일시
    
    Authentication:
        JWT 인증 필요
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Fittings"],
        summary="가상 피팅 결과 조회",
        description="완료된 가상 피팅 결과(이미지 URL 등)를 조회합니다.",
        responses={200: FittingResultSerializer}
    )
    def get(self, request, fitting_image_id):
        """피팅 결과를 조회합니다."""
        with create_span(TRACER_NAME, "api_fitting_result") as span:
            span.set("fitting.id", fitting_image_id)

            fitting = get_object_or_404(FittingImage, id=fitting_image_id)
            span.set("fitting.status", fitting.fitting_image_status)
            
            if fitting.fitting_image_url:
                span.set("fitting.has_result", True)

            serializer = FittingResultSerializer(fitting)
            return Response(serializer.data, status=status.HTTP_200_OK)
