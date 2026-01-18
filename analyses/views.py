"""
analyses 앱 Views.

리팩토링:
- 중복 tracer 초기화 제거
- 상수 모듈 활용 (constants.py)
- 공통 유틸리티 활용 (utils.py)
"""

import logging
import uuid

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from services.metrics import IMAGES_UPLOADED_TOTAL

from .models import UploadedImage, ImageAnalysis, DetectedObject
from .serializers import (
    UploadedImageCreateSerializer,
    UploadedImageResponseSerializer,
    UploadedImageListSerializer,
    ImageAnalysisCreateSerializer,
    ImageAnalysisResponseSerializer,
    ImageAnalysisStatusSerializer,
    ImageAnalysisResultSerializer,
    AnalysisRefineRequestSerializer,
    AnalysisRefineResponseSerializer,
    HistoryItemSerializer,
)
from .tasks import (
    process_image_analysis,
    parse_refine_query_task,
    refine_single_object,
    upload_image_to_gcs_task,
)
from .constants import CATEGORY_ALIASES
from .utils import create_span, expand_category_aliases

from services import get_redis_service


logger = logging.getLogger(__name__)

# 트레이서 모듈명
TRACER_NAME = "analyses.views"


class UploadedImageView(APIView):
    """
    이미지 업로드 API

    POST /api/v1/uploaded-images - 이미지 업로드
    GET /api/v1/uploaded-images - 업로드 이력 조회
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="이미지 업로드",
        description="분석할 이미지를 업로드합니다 (최대 10MB).",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'file': {
                        'type': 'string',
                        'format': 'binary',
                        'description': '분석할 이미지 파일 (JPG, PNG, WEBP)'
                    }
                },
                'required': ['file']
            }
        },
        responses={201: UploadedImageResponseSerializer}
    )
    def post(self, request):
        """
        이미지 업로드 (Celery 비동기 처리)
        """
        import base64
        from .constants import ImageConfig

        with create_span(TRACER_NAME, "api_upload_image") as ctx:
            ctx.set("http.method", "POST")
            ctx.set("api.endpoint", "/api/v1/uploaded-images")

            # 1. 파일 유효성 검사
            file = request.FILES.get('file')
            if not file:
                return Response(
                    {'error': {'file': ['파일이 필요합니다.']}},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 파일 크기 제한
            if file.size > ImageConfig.MAX_FILE_SIZE_MB * 1024 * 1024:
                return Response(
                    {'error': {'file': [f'파일 크기는 {ImageConfig.MAX_FILE_SIZE_MB}MB 이하여야 합니다.']}},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 허용된 파일 형식 검사
            if file.content_type not in ImageConfig.ALLOWED_CONTENT_TYPES:
                return Response(
                    {'error': {'file': ['JPG, PNG, WEBP 파일만 업로드 가능합니다.']}},
                    status=status.HTTP_400_BAD_REQUEST
                )

            ctx.set("file.name", file.name)
            ctx.set("file.size", file.size)
            ctx.set("file.content_type", file.content_type)

            # 2. 파일을 Base64로 인코딩 (Celery 전달용)
            file_bytes = file.read()
            image_b64 = base64.b64encode(file_bytes).decode('utf-8')

            # 3. 사용자 ID 가져오기
            user_id = request.user.id if request.user.is_authenticated else None

            # 4. Celery 태스크로 GCS 업로드
            try:
                from opentelemetry.propagate import inject
                headers = {}
                inject(headers)

                result = upload_image_to_gcs_task.apply_async(
                    args=[image_b64, file.name, file.content_type, user_id],
                    headers=headers,
                ).get(timeout=60)

                logger.info(f"Image uploaded via Celery: {result.get('uploaded_image_id')}")
                IMAGES_UPLOADED_TOTAL.inc()

                ctx.set("uploaded_image_id", result.get('uploaded_image_id'))
                ctx.set("status", "success")

                return Response(result, status=status.HTTP_201_CREATED)

            except Exception as e:
                logger.error(f"Failed to upload image: {e}")
                ctx.set("error", str(e))
                ctx.set("status", "failed")

                return Response(
                    {'error': f'이미지 업로드 중 오류가 발생했습니다: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

    @extend_schema(
        tags=["Analyses"],
        summary="업로드 이미지 이력 조회",
        description="사용자가 업로드한 이미지들의 이력을 조회합니다 (커서 기반 페이지네이션).",
        parameters=[
            OpenApiParameter("cursor", type=int, description="이전 페이지의 마지막 ID"),
            OpenApiParameter("limit", type=int, default=10, description="한 페이지당 아이템 수")
        ],
        responses={200: OpenApiResponse(description="이미지 목록")}
    )
    def get(self, request):
        """업로드 이미지 이력 조회"""
        cursor = request.query_params.get('cursor')
        limit = int(request.query_params.get('limit', 10))

        queryset = UploadedImage.objects.filter(
            user=request.user,
            is_deleted=False
        )

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        images = list(queryset.order_by('-id')[:limit + 1])

        has_next = len(images) > limit
        if has_next:
            images = images[:limit]

        next_cursor = images[-1].id if has_next and images else None

        serializer = UploadedImageListSerializer(images, many=True)

        return Response({
            'items': serializer.data,
            'next_cursor': next_cursor
        })


class ImageAnalysisView(APIView):
    """
    이미지 분석 API

    POST /api/v1/analyses - 이미지 분석 시작
    PATCH /api/v1/analyses - 자연어 기반 결과 수정
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="자연어 기반 결과 수정 (재분석)",
        description="사용자의 자연어 요청에 따라 특정 카테고리나 객체를 다시 검색합니다.",
        request=AnalysisRefineRequestSerializer,
        responses={200: AnalysisRefineResponseSerializer}
    )
    def patch(self, request):
        """자연어 기반 결과 수정 (API 6)"""
        from celery import group

        # 1. 요청 유효성 검사
        serializer = AnalysisRefineRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        analysis_id = serializer.validated_data['analysis_id']
        query = serializer.validated_data['query']
        detected_object_id = serializer.validated_data.get('detected_object_id')

        # 2. 분석 결과 조회
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

        # 3. 대상 객체 결정
        detected_objects = self._get_target_objects(analysis, detected_object_id)
        if not detected_objects.exists():
            return Response(
                {'error': '검출된 객체가 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # 4. LangChain 쿼리 파싱
        available_categories = list(
            detected_objects.values_list('object_category', flat=True).distinct()
        )
        parsed_query = self._parse_query(query, available_categories)

        # 5. 대상 카테고리 필터링
        target_objects = self._filter_by_categories(
            detected_objects, parsed_query.get('target_categories', [])
        )
        target_object_ids = list(target_objects.values_list('id', flat=True))

        # 6. Celery Group으로 병렬 처리
        refine_id = str(uuid.uuid4())
        try:
            from opentelemetry.propagate import inject
            refine_headers = {}
            inject(refine_headers)

            subtasks = [
                refine_single_object.s(
                    refine_id=refine_id,
                    detected_object_id=obj_id,
                    parsed_query=parsed_query,
                ).set(headers=refine_headers)
                for obj_id in target_object_ids
            ]

            if subtasks:
                job = group(subtasks)
                results = job.apply_async().get(timeout=300)
                logger.info(f"Refine completed: {len(results)} objects processed")

        except Exception as e:
            logger.error(f"Failed to process refine tasks: {e}")
            return Response(
                {'error': f'재분석 처리 중 오류가 발생했습니다: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 7. 최신 데이터로 응답 반환
        analysis.refresh_from_db()
        response_serializer = AnalysisRefineResponseSerializer(analysis)
        return Response(response_serializer.data)

    def _get_target_objects(self, analysis, detected_object_id):
        """대상 객체 조회."""
        if detected_object_id:
            return analysis.uploaded_image.detected_objects.filter(
                id=detected_object_id, is_deleted=False
            )
        return analysis.uploaded_image.detected_objects.filter(is_deleted=False)

    def _parse_query(self, query, available_categories):
        """LangChain 쿼리 파싱."""
        try:
            from opentelemetry.propagate import inject
            headers = {}
            inject(headers)

            parsed_query = parse_refine_query_task.apply_async(
                args=[query, available_categories],
                headers=headers,
            ).get(timeout=30)

            logger.info(f"Parsed refine query: {parsed_query}")
            return parsed_query

        except Exception as e:
            logger.error(f"LangChain parsing failed: {e}")
            return {
                'action': 'research',
                'target_categories': available_categories,
                'search_keywords': None,
                'brand_filter': None,
                'price_filter': None,
                'style_keywords': [],
            }

    def _filter_by_categories(self, detected_objects, target_categories):
        """카테고리로 객체 필터링."""
        if not target_categories:
            return detected_objects

        # 공통 유틸리티로 카테고리 확장
        mapped_categories = expand_category_aliases(target_categories)

        target_objects = detected_objects.filter(
            object_category__in=list(mapped_categories)
        )

        logger.info(
            f"Target categories: {target_categories} → mapped: {mapped_categories}, "
            f"found {target_objects.count()} objects"
        )

        # 매칭되는 객체가 없으면 전체 대상
        if not target_objects.exists():
            logger.info(f"No objects matched categories, using all {detected_objects.count()} objects")
            return detected_objects

        return target_objects

    @extend_schema(
        tags=["Analyses"],
        summary="이미지 분석 시작",
        description="업로드된 이미지를 기반으로 AI 분석을 시작합니다 (비동기 처리).",
        request=ImageAnalysisCreateSerializer,
        responses={201: ImageAnalysisResponseSerializer}
    )
    def post(self, request):
        """이미지 분석 시작"""
        with create_span(TRACER_NAME, "api_start_analysis") as ctx:
            ctx.set("http.method", "POST")
            ctx.set("api.endpoint", "/api/v1/analyses")

            serializer = ImageAnalysisCreateSerializer(data=request.data)

            if not serializer.is_valid():
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            analysis = serializer.save()

            ctx.set("analysis_id", analysis.id)
            ctx.set("uploaded_image_id", analysis.uploaded_image.id)

            # 이미지 URL 가져오기
            uploaded_image = analysis.uploaded_image
            image_url = request.data.get('uploaded_image_url')
            if not image_url and uploaded_image.uploaded_image_url:
                image_url = uploaded_image.uploaded_image_url.url

            # Celery task 트리거
            try:
                from opentelemetry.propagate import inject
                headers = {}
                inject(headers)

                process_image_analysis.apply_async(
                    args=[str(analysis.id), image_url],
                    kwargs={'user_id': request.user.id if request.user.is_authenticated else None},
                    headers=headers,
                )
                logger.info(f"Analysis task triggered: {analysis.id}")
                ctx.set("task_triggered", True)
            except Exception as e:
                logger.error(f"Failed to trigger analysis task: {e}")
                ctx.set("task_triggered", False)
                ctx.set("error", str(e))

            response_serializer = ImageAnalysisResponseSerializer(analysis)
            return Response(
                response_serializer.data,
                status=status.HTTP_201_CREATED
            )


class AnalysisRefineStatusView(APIView):
    """자연어 재분석 상태 조회 API"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="자연어 재분석 상태 조회",
        description="요청한 재분석 작업의 현재 진행 상태를 조회합니다.",
        parameters=[
            OpenApiParameter("refine_id", type=str, required=True, description="재분석 요청 UUID")
        ],
        responses={200: OpenApiResponse(description="작업 상태 정보")}
    )
    def get(self, request, analysis_id):
        """재분석 작업 상태 조회"""
        refine_id = request.query_params.get('refine_id')
        if not refine_id:
            return Response(
                {'error': 'refine_id가 필요합니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        redis_service = get_redis_service()

        refine_status = redis_service.get(f"refine:{refine_id}:status")
        if not refine_status:
            return Response(
                {'error': '존재하지 않거나 만료된 재분석 작업입니다.'},
                status=status.HTTP_404_NOT_FOUND
            )

        total = redis_service.get(f"refine:{refine_id}:total") or "0"
        completed = redis_service.get(f"refine:{refine_id}:completed") or "0"

        response_data = {
            'refine_id': refine_id,
            'analysis_id': analysis_id,
            'status': refine_status,
            'progress': int(completed),
            'total': int(total),
        }

        if refine_status == 'DONE':
            response_data['success_count'] = int(redis_service.get(f"refine:{refine_id}:success_count") or "0")
            response_data['failed_count'] = int(redis_service.get(f"refine:{refine_id}:failed_count") or "0")
            response_data['total_mappings'] = int(redis_service.get(f"refine:{refine_id}:total_mappings") or "0")
        elif refine_status == 'FAILED':
            response_data['error'] = redis_service.get(f"refine:{refine_id}:error")

        return Response(response_data)


class ImageAnalysisStatusView(APIView):
    """이미지 분석 상태 조회 API"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="이미지 분석 상태 조회",
        description="이미지 분석 작업의 현재 상태 및 진행률을 조회합니다.",
        responses={200: ImageAnalysisStatusSerializer}
    )
    def get(self, request, analysis_id):
        """이미지 분석 상태 조회"""
        try:
            analysis = ImageAnalysis.objects.get(id=analysis_id, is_deleted=False)
        except ImageAnalysis.DoesNotExist:
            return Response(
                {'error': '존재하지 않는 분석입니다.'},
                status=status.HTTP_404_NOT_FOUND
            )

        redis_service = get_redis_service()
        progress = redis_service.get_analysis_progress(str(analysis_id))

        redis_status = redis_service.get_analysis_status(str(analysis_id))
        if redis_status:
            analysis.image_analysis_status = redis_status

        serializer = ImageAnalysisStatusSerializer(analysis)
        data = serializer.data
        data['progress'] = progress

        return Response(data)


class ImageAnalysisResultView(APIView):
    """이미지 분석 결과 조회 API"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="이미지 분석 결과 조회",
        description="완료된 이미지 분석 결과를 조회합니다.",
        responses={200: ImageAnalysisResultSerializer}
    )
    def get(self, request, analysis_id):
        """이미지 분석 결과 조회"""
        with create_span(TRACER_NAME, "api_get_analysis_result") as ctx:
            ctx.set("http.method", "GET")
            ctx.set("api.endpoint", f"/api/v1/analyses/{analysis_id}")
            ctx.set("analysis_id", analysis_id)

            try:
                analysis = ImageAnalysis.objects.select_related(
                    'uploaded_image'
                ).prefetch_related(
                    'uploaded_image__detected_objects',
                    'uploaded_image__detected_objects__product_mappings',
                    'uploaded_image__detected_objects__product_mappings__product',
                ).get(id=analysis_id, is_deleted=False)
            except ImageAnalysis.DoesNotExist:
                ctx.set("error", "analysis_not_found")
                return Response(
                    {'error': '존재하지 않는 분석입니다.'},
                    status=status.HTTP_404_NOT_FOUND
                )

            ctx.set("status", analysis.image_analysis_status)
            detected_count = analysis.uploaded_image.detected_objects.count()
            ctx.set("detected_objects_count", detected_count)

            serializer = ImageAnalysisResultSerializer(analysis)
            return Response(serializer.data)


class UploadedImageHistoryView(APIView):
    """통합 히스토리 조회 API"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="통합 히스토리 조회",
        description="업로드된 이미지에 대한 검출 객체, 매칭 상품, 피팅 정보를 통합 조회합니다.",
        parameters=[
            OpenApiParameter("cursor", type=str, description="페이지네이션용 커서"),
            OpenApiParameter("limit", type=int, default=10, description="페이지당 아이템 수")
        ],
        responses={200: OpenApiResponse(description="히스토리 목록")}
    )
    def get(self, request, uploaded_image_id):
        """통합 히스토리 조회"""
        try:
            uploaded_image = UploadedImage.objects.get(
                id=uploaded_image_id,
                user=request.user,
                is_deleted=False
            )
        except UploadedImage.DoesNotExist:
            return Response(
                {'error': '존재하지 않는 이미지입니다.'},
                status=status.HTTP_404_NOT_FOUND
            )

        cursor = request.query_params.get('cursor')
        limit = int(request.query_params.get('limit', 10))

        queryset = DetectedObject.objects.filter(
            uploaded_image=uploaded_image,
            is_deleted=False
        ).prefetch_related(
            'product_mappings',
            'product_mappings__product',
            'product_mappings__product__size_codes',
            'product_mappings__product__size_codes__selections',
        ).order_by('-id')

        if cursor:
            try:
                queryset = queryset.filter(id__lt=int(cursor))
            except ValueError:
                pass

        detected_objects = list(queryset[:limit + 1])

        has_next = len(detected_objects) > limit
        if has_next:
            detected_objects = detected_objects[:limit]

        next_cursor = str(detected_objects[-1].id) if has_next and detected_objects else None

        items = HistoryItemSerializer(detected_objects, many=True).data

        response_data = {'items': items}
        if next_cursor:
            response_data['next_cursor'] = next_cursor

        return Response(response_data)
