import logging

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser

from .models import UploadedImage, ImageAnalysis
from .serializers import (
    UploadedImageCreateSerializer,
    UploadedImageResponseSerializer,
    UploadedImageListSerializer,
    ImageAnalysisCreateSerializer,
    ImageAnalysisResponseSerializer,
    ImageAnalysisStatusSerializer,
    ImageAnalysisResultSerializer,
)
from .tasks import process_image_analysis
from services import get_redis_service

logger = logging.getLogger(__name__)


class UploadedImageView(APIView):
    """
    이미지 업로드 API
    
    POST /api/v1/uploaded-images - 이미지 업로드
    GET /api/v1/uploaded-images - 업로드 이력 조회
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [AllowAny]  # 일단 누구나 접근 가능하게

    def post(self, request):
        """
        이미지 업로드
        Request: multipart/form-data { file: 이미지 }
        Response 201: { uploaded_image_id, uploaded_image_url, created_at }
        """
        serializer = UploadedImageCreateSerializer(
            data=request.data,
            context={'request': request}
        )

        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        uploaded_image = serializer.save()

        response_serializer = UploadedImageResponseSerializer(uploaded_image)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED
        )

    def get(self, request):
        """
        업로드 이미지 이력 조회
        Query Params: cursor (페이지네이션), limit (기본 10)
        Response 200: { items: [...], next_cursor }
        """
        # Query parameters
        cursor = request.query_params.get('cursor')
        limit = int(request.query_params.get('limit', 10))

        # 삭제되지 않은 이미지만 조회
        queryset = UploadedImage.objects.filter(is_deleted=False)

        # cursor가 있으면 그 이후부터 조회
        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        # limit + 1개 조회 (다음 페이지 있는지 확인용)
        images = queryset.order_by('-id')[:limit + 1]
        images = list(images)

        # 다음 페이지 존재 여부 확인
        has_next = len(images) > limit
        if has_next:
            images = images[:limit]  # 실제로는 limit개만 반환

        # 다음 cursor 계산
        next_cursor = None
        if has_next and images:
            next_cursor = images[-1].id

        serializer = UploadedImageListSerializer(images, many=True)

        return Response({
            'items': serializer.data,
            'next_cursor': next_cursor
        })


class ImageAnalysisView(APIView):
    """
    이미지 분석 API

    POST /api/v1/analyses - 이미지 분석 시작
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """
        이미지 분석 시작

        Request Body: { uploaded_image_id: int, uploaded_image_url: string }
        Response 201: { analysis_id, status, polling: { status_url, result_url } }
        """
        serializer = ImageAnalysisCreateSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ImageAnalysis 레코드 생성
        analysis = serializer.save()

        # 이미지 URL 가져오기
        uploaded_image = analysis.uploaded_image
        image_url = request.data.get('uploaded_image_url')
        if not image_url and uploaded_image.uploaded_image_url:
            image_url = uploaded_image.uploaded_image_url.url

        # Celery task 트리거
        try:
            process_image_analysis.delay(
                analysis_id=str(analysis.id),
                image_url=image_url,
                user_id=request.user.id if request.user.is_authenticated else None,
            )
            logger.info(f"Analysis task triggered: {analysis.id}")
        except Exception as e:
            logger.error(f"Failed to trigger analysis task: {e}")
            # 실패해도 일단 응답은 반환 (상태는 PENDING으로 유지)

        response_serializer = ImageAnalysisResponseSerializer(analysis)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED
        )

class ImageAnalysisStatusView(APIView):
    """
    이미지 분석 상태 조회 API

    GET /api/v1/analyses/{analysis_id}/status
    """
    permission_classes = [AllowAny]

    def get(self, request, analysis_id):
        """
        이미지 분석 상태 조회

        Response 200: { analysis_id, status, progress, updated_at }
        """
        # DB에서 분석 정보 조회
        try:
            analysis = ImageAnalysis.objects.get(id=analysis_id, is_deleted=False)
        except ImageAnalysis.DoesNotExist:
            return Response(
                {'error': '존재하지 않는 분석입니다.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Redis에서 실시간 진행률 조회
        redis_service = get_redis_service()
        progress = redis_service.get_analysis_progress(str(analysis_id))

        # Redis에서 상태도 조회 (더 최신일 수 있음)
        redis_status = redis_service.get_analysis_status(str(analysis_id))
        if redis_status:
            analysis.image_analysis_status = redis_status

        # Serializer에 progress 추가하여 응답
        serializer = ImageAnalysisStatusSerializer(analysis)
        data = serializer.data
        data['progress'] = progress

        return Response(data)


class ImageAnalysisResultView(APIView):
    """
    이미지 분석 결과 조회 API

    GET /api/v1/analyses/{analysis_id}
    """
    permission_classes = [AllowAny]

    def get(self, request, analysis_id):
        """
        이미지 분석 결과 조회

        Response 200: {
            analysis_id, uploaded_image, status, items: [
                { detected_object_id, category_name, bbox, match }
            ]
        }
        """
        # DB에서 분석 정보 조회 (관련 데이터 prefetch)
        try:
            analysis = ImageAnalysis.objects.select_related(
                'uploaded_image'
            ).prefetch_related(
                'uploaded_image__detected_objects',
                'uploaded_image__detected_objects__product_mappings',
                'uploaded_image__detected_objects__product_mappings__product',
            ).get(id=analysis_id, is_deleted=False)
        except ImageAnalysis.DoesNotExist:
            return Response(
                {'error': '존재하지 않는 분석입니다.'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = ImageAnalysisResultSerializer(analysis)
        return Response(serializer.data)
