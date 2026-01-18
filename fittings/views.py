import logging
from contextlib import nullcontext

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from django.shortcuts import get_object_or_404
from .models import FittingImage, UserImage
from .serializers import (
    FittingImageSerializer,
    FittingStatusSerializer,
    FittingResultSerializer,
    UserImageUploadSerializer
)
from .tasks import process_fitting_task

logger = logging.getLogger(__name__)


def _get_tracer():
    """Get tracer lazily to ensure TracerProvider is initialized."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("fittings.views")
    except ImportError:
        return None


def _create_span(name: str):
    """Create a span if tracer is available."""
    tracer = _get_tracer()
    if tracer:
        return tracer.start_as_current_span(name)
    return nullcontext()


class UserImageUploadView(APIView):
    """
    [POST] 사용자 전신 이미지 업로드
    POST /api/v1/user-images

    파일을 업로드하면 URL로 변환하여 저장 후 반환
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
        with _create_span("api_user_image_upload") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)

            serializer = UserImageUploadSerializer(
                data=request.data,
                context={'request': request}
            )

            if serializer.is_valid():
                user_image = serializer.save()
                logger.info(f"User image uploaded: {user_image.id}")
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("user_image.id", user_image.id)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class FittingRequestView(APIView):
    """
    [POST] 가상 피팅 요청
    POST /api/v1/fitting-images

    동일한 (user_image, product) 조합에 대해 완료된 피팅이 있으면
    API 호출 없이 기존 결과를 재사용합니다.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Fittings"],
        summary="가상 피팅 요청",
        description="사용자 이미지와 상품 정보를 바탕으로 가상 피팅을 요청합니다. 동일한 조합의 결과가 이미 있으면 기존 결과를 반환합니다.",
        request=FittingImageSerializer,
        responses={
            201: FittingImageSerializer,
            200: FittingResultSerializer  # 캐싱된 결과 반환 시
        }
    )
    def post(self, request):
        with _create_span("api_fitting_request") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)

            serializer = FittingImageSerializer(
                data=request.data,
                context={'request': request}
            )

            if serializer.is_valid():
                user_image = serializer.validated_data.get('user_image_url')
                product = serializer.validated_data.get('product')

                # 캐싱: 동일한 조합의 완료된 피팅이 있는지 확인
                existing_fitting = FittingImage.objects.filter(
                    user_image=user_image,
                    product=product,
                    fitting_image_status=FittingImage.Status.DONE,
                    is_deleted=False
                ).first()

                if existing_fitting:
                    logger.info(f"Fitting cache hit: {existing_fitting.id}")
                    if span and hasattr(span, 'set_attribute'):
                        span.set_attribute("fitting.cache_hit", True)
                        span.set_attribute("fitting.id", existing_fitting.id)
                    result_serializer = FittingResultSerializer(existing_fitting)
                    return Response(result_serializer.data, status=status.HTTP_200_OK)

                # 신규 피팅 생성
                fitting = serializer.save(fitting_image_status=FittingImage.Status.PENDING)

                # Inject trace context for Celery
                from opentelemetry.propagate import inject
                headers = {}
                inject(headers)
                process_fitting_task.apply_async(args=[fitting.id], headers=headers)

                logger.info(f"Fitting request created: {fitting.id}")
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("fitting.cache_hit", False)
                    span.set_attribute("fitting.id", fitting.id)

                return Response(serializer.data, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class FittingStatusView(APIView):
    """
    [GET] 가상 피팅 상태 조회
    GET /api/v1/fitting-images/{fitting_image_id}/status
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Fittings"],
        summary="가상 피팅 상태 조회",
        description="요청한 가상 피팅 작업의 현재 상태를 조회합니다.",
        responses={200: FittingStatusSerializer}
    )
    def get(self, request, fitting_image_id):
        with _create_span("api_fitting_status") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("fitting.id", fitting_image_id)

            fitting = get_object_or_404(FittingImage, id=fitting_image_id)

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("fitting.status", fitting.fitting_image_status)

            serializer = FittingStatusSerializer(fitting)
            return Response(serializer.data, status=status.HTTP_200_OK)


class FittingResultView(APIView):
    """
    [GET] 가상 피팅 결과 조회
    GET /api/v1/fitting-images/{fitting_image_id}
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Fittings"],
        summary="가상 피팅 결과 조회",
        description="완료된 가상 피팅 결과(이미지 URL 등)를 조회합니다.",
        responses={200: FittingResultSerializer}
    )
    def get(self, request, fitting_image_id):
        with _create_span("api_fitting_result") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("fitting.id", fitting_image_id)

            fitting = get_object_or_404(FittingImage, id=fitting_image_id)

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("fitting.status", fitting.fitting_image_status)
                if fitting.fitting_image_url:
                    span.set_attribute("fitting.has_result", True)

            serializer = FittingResultSerializer(fitting)
            return Response(serializer.data, status=status.HTTP_200_OK)
