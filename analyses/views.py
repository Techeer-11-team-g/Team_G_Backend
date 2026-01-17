import logging
import uuid

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, OpenApiExample

from services.metrics import IMAGES_UPLOADED_TOTAL

# OpenTelemetry for custom tracing spans
try:
    from opentelemetry import trace
    tracer = trace.get_tracer("analyses.views")
except ImportError:
    tracer = None


def create_span(name):
    """Helper for creating spans (handles case when tracer is None)."""
    if tracer:
        return tracer.start_as_current_span(name)
    from contextlib import nullcontext
    return nullcontext()
from .models import UploadedImage, ImageAnalysis, ObjectProductMapping, DetectedObject
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
from services import get_redis_service

# OpenTelemetry Tracer 설정
try:
    from opentelemetry import trace
    tracer = trace.get_tracer("analyses.views.uploaded_image")
except ImportError:
    tracer = None

logger = logging.getLogger(__name__)


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

        GCS 업로드를 Celery 워커에서 처리하여 웹 워커 부하 감소.

        Request: multipart/form-data { file: 이미지 }
        Response 201: { uploaded_image_id, uploaded_image_url, created_at }
        """
        import base64

        with create_span("api_upload_image") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("http.method", "POST")
                span.set_attribute("api.endpoint", "/api/v1/uploaded-images")

            # 1. 파일 유효성 검사
            file = request.FILES.get('file')
            if not file:
                return Response(
                    {'error': {'file': ['파일이 필요합니다.']}},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 파일 크기 제한: 10MB
            if file.size > 10 * 1024 * 1024:
                return Response(
                    {'error': {'file': ['파일 크기는 10MB 이하여야 합니다.']}},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 허용된 파일 형식 검사
            allowed_types = ['image/jpeg', 'image/png', 'image/webp']
            if file.content_type not in allowed_types:
                return Response(
                    {'error': {'file': ['JPG, PNG, WEBP 파일만 업로드 가능합니다.']}},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("file.name", file.name)
                span.set_attribute("file.size", file.size)
                span.set_attribute("file.content_type", file.content_type)

            # 2. 파일을 Base64로 인코딩 (Celery 전달용)
            file_bytes = file.read()
            image_b64 = base64.b64encode(file_bytes).decode('utf-8')

            # 3. 사용자 ID 가져오기
            user_id = request.user.id if request.user.is_authenticated else None

            # 4. Celery 태스크로 GCS 업로드 (외부 API 호출)
            try:
                result = upload_image_to_gcs_task.apply_async(
                    args=[image_b64, file.name, file.content_type, user_id]
                ).get(timeout=60)  # 60초 타임아웃

                logger.info(f"Image uploaded via Celery: {result.get('uploaded_image_id')}")
                IMAGES_UPLOADED_TOTAL.inc()

                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("uploaded_image_id", result.get('uploaded_image_id'))
                    span.set_attribute("status", "success")

                return Response(result, status=status.HTTP_201_CREATED)

            except Exception as e:
                # 1. 로그 기록 (개발자/운영자용): 텍스트 로그 파일에 남겨서 나중에 원인 분석
                logger.error(f"Failed to upload image: {e}")

                # 2. 트레이스 기록 (모니터링용 - OpenTelemetry):
                #    - OTel 라이브러리가 로드되어 있고(status), Span이 생성된 상태라면 에러 정보를 태그로 부착
                #    - Jaeger 같은 모니터링 도구에서 '빨간색(Failed)'으로 시각화되어 쉽게 확인 가능
                #    - 만약 OTel이 설정 안 되어 있다면 span은 빈 껍데기(No-op) 객체이거나 None이므로 안전하게 무시됨(hasattr 체크)
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("error", str(e))
                    span.set_attribute("status", "failed")

                # 3. 사용자 응답 (프론트엔드용): 500 에러와 함께 안내 메시지 전달
                return Response(
                    {'error': f'이미지 업로드 중 오류가 발생했습니다: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

    @extend_schema(
        tags=["Analyses"],
        summary="업로드 이미지 이력 조회",
        description="사용자가 업로드한 이미지들의 이력을 조회합니다 (커서 기반 페이지네이션).",
        parameters=[
            OpenApiParameter("cursor", type=int, description="이전 페이지의 마지막 ID (첫 페이지는 비워둠)"),
            OpenApiParameter("limit", type=int, default=10, description="한 페이지당 아이템 수")
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'items': { 'type': 'array', 'items': { '$ref': '#/components/schemas/UploadedImageList' } },
                    'next_cursor': { 'type': 'integer', 'nullable': True }
                }
            }
        }
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
        """
        자연어 기반 결과 수정 (API 6)

        모든 외부 API 호출을 Celery로 비동기 병렬 처리:
        1. LangChain 쿼리 파싱 (Celery 태스크)
        2. 객체별 재검색 (Celery Group 병렬)

        Request Body: {
            analysis_id: int,
            query: string (예: "상의만 다시 검색해줘"),
            detected_object_id: int (optional - 특정 객체만 재검색)
        }
        Response (200 OK, DONE): {
            analysis_id: int,
            status: "DONE",
            image: { uploaded_image_id, uploaded_image_url },
            items: [{ detected_object_id, category_name, confidence_score, bbox, match }]
        }
        """
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
        if detected_object_id:
            detected_objects = analysis.uploaded_image.detected_objects.filter(
                id=detected_object_id, is_deleted=False
            )
        else:
            detected_objects = analysis.uploaded_image.detected_objects.filter(
                is_deleted=False
            )

        if not detected_objects.exists():
            return Response(
                {'error': '검출된 객체가 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # 4. LangChain 쿼리 파싱 (Celery 비동기 - 외부 API: OpenAI)
        available_categories = list(detected_objects.values_list('object_category', flat=True).distinct())

        try:
            # Celery 태스크로 LangChain 파싱 실행 (timeout: 30초)
            parsed_query = parse_refine_query_task.apply_async(
                args=[query, available_categories]
            ).get(timeout=30)

            logger.info(f"Parsed refine query (async): {parsed_query}")

        except Exception as e:
            logger.error(f"LangChain parsing failed: {e}")
            # 파싱 실패 시 기본값 사용
            parsed_query = {
                'action': 'research',
                'target_categories': available_categories,
                'search_keywords': None,
                'brand_filter': None,
                'price_filter': None,
                'style_keywords': [],
            }

        # 5. 대상 카테고리 필터링 (LangChain 출력 → DB 카테고리 매핑)
        target_categories = parsed_query.get('target_categories', [])

        if target_categories:
            # 카테고리 매핑: LangChain 출력값 → DB에 저장된 object_category 값들
            category_aliases = {
                'pants': ['pants', 'bottom', '하의', '바지'],
                'bottom': ['pants', 'bottom', '하의', '바지'],
                'top': ['top', '상의', '티셔츠', '셔츠'],
                'outer': ['outer', 'outerwear', '아우터', '자켓', '코트'],
                'outerwear': ['outer', 'outerwear', '아우터', '자켓', '코트'],
                'shoes': ['shoes', '신발', '운동화', '스니커즈'],
                'bag': ['bag', '가방'],
            }

            # 매핑된 카테고리 목록 생성
            mapped_categories = set()
            for cat in target_categories:
                cat_lower = cat.lower()
                if cat_lower in category_aliases:
                    mapped_categories.update(category_aliases[cat_lower])
                else:
                    mapped_categories.add(cat)

            target_objects = detected_objects.filter(object_category__in=list(mapped_categories))
            logger.info(f"Target categories: {target_categories} → mapped: {mapped_categories}, found {target_objects.count()} objects")

            # 매칭되는 객체가 없으면 전체 대상
            if not target_objects.exists():
                target_objects = detected_objects
                logger.info(f"No objects matched categories, using all {target_objects.count()} objects")
        else:
            target_objects = detected_objects

        target_object_ids = list(target_objects.values_list('id', flat=True))

        # 6. Celery Group으로 병렬 처리 (외부 API: CLIP, OpenSearch)
        refine_id = str(uuid.uuid4())
        try:
            # 각 객체별 서브태스크 생성
            subtasks = [
                refine_single_object.s(
                    refine_id=refine_id,
                    detected_object_id=obj_id,
                    parsed_query=parsed_query,
                )
                for obj_id in target_object_ids
            ]

            # 병렬 실행 후 완료 대기 (timeout: 5분)
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

        # 7. 최신 데이터로 응답 반환 (명세서 형식)
        analysis.refresh_from_db()
        response_serializer = AnalysisRefineResponseSerializer(analysis)
        return Response(response_serializer.data)

    @extend_schema(
        tags=["Analyses"],
        summary="이미지 분석 시작",
        description="업로드된 이미지를 기반으로 AI 분석을 시작합니다 (비동기 처리).",
        request=ImageAnalysisCreateSerializer,
        responses={201: ImageAnalysisResponseSerializer}
    )
    def post(self, request):
        """
        이미지 분석 시작

        Request Body: { uploaded_image_id: int, uploaded_image_url: string }
        Response 201: { analysis_id, status, polling: { status_url, result_url } }
        """
        with create_span("api_start_analysis") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("http.method", "POST")
                span.set_attribute("api.endpoint", "/api/v1/analyses")

            serializer = ImageAnalysisCreateSerializer(data=request.data)

            if not serializer.is_valid():
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # ImageAnalysis 레코드 생성
            analysis = serializer.save()

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("analysis_id", analysis.id)
                span.set_attribute("uploaded_image_id", analysis.uploaded_image.id)

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
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("task_triggered", True)
            except Exception as e:
                logger.error(f"Failed to trigger analysis task: {e}")
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("task_triggered", False)
                    span.set_attribute("error", str(e))
                # 실패해도 일단 응답은 반환 (상태는 PENDING으로 유지)

            response_serializer = ImageAnalysisResponseSerializer(analysis)
            return Response(
                response_serializer.data,
                status=status.HTTP_201_CREATED
            )

class AnalysisRefineStatusView(APIView):
    """
    자연어 재분석 상태 조회 API

    GET /api/v1/analyses/{analysis_id}/refine-status?refine_id={refine_id}
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="자연어 재분석 상태 조회",
        description="요청한 재분석 작업의 현재 진행 상태를 조회합니다.",
        parameters=[
            OpenApiParameter("refine_id", type=str, required=True, description="재분석 요청 시 발급받은 UUID")
        ],
        responses={200: OpenApiResponse(description="작업 상태 정보")}
    )
    def get(self, request, analysis_id):
        """
        재분석 작업 상태 조회

        Query Params: refine_id (required)
        Response 200: {
            refine_id, analysis_id, status, progress, total,
            success_count, failed_count (완료 시)
        }
        """
        refine_id = request.query_params.get('refine_id')
        if not refine_id:
            return Response(
                {'error': 'refine_id가 필요합니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        redis_service = get_redis_service()

        # Redis에서 상태 조회
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

        # 완료된 경우 추가 정보
        if refine_status == 'DONE':
            response_data['success_count'] = int(redis_service.get(f"refine:{refine_id}:success_count") or "0")
            response_data['failed_count'] = int(redis_service.get(f"refine:{refine_id}:failed_count") or "0")
            response_data['total_mappings'] = int(redis_service.get(f"refine:{refine_id}:total_mappings") or "0")
        elif refine_status == 'FAILED':
            response_data['error'] = redis_service.get(f"refine:{refine_id}:error")

        return Response(response_data)


class ImageAnalysisStatusView(APIView):
    """
    이미지 분석 상태 조회 API

    GET /api/v1/analyses/{analysis_id}/status
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="이미지 분석 상태 조회",
        description="이미지 분석 작업의 현재 상태(PENDING, RUNNING, DONE, FAILED) 및 진행률을 조회합니다.",
        responses={200: ImageAnalysisStatusSerializer}
    )
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
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="이미지 분석 결과 조회",
        description="완료된 이미지 분석 결과 (검출된 객체 및 매칭 상품 정보)를 조회합니다.",
        responses={200: ImageAnalysisResultSerializer}
    )
    def get(self, request, analysis_id):
        """
        이미지 분석 결과 조회

        Response 200: {
            analysis_id, uploaded_image, status, items: [
                { detected_object_id, category_name, bbox, match }
            ]
        }
        """
        with create_span("api_get_analysis_result") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("http.method", "GET")
                span.set_attribute("api.endpoint", f"/api/v1/analyses/{analysis_id}")
                span.set_attribute("analysis_id", analysis_id)

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
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("error", "analysis_not_found")
                return Response(
                    {'error': '존재하지 않는 분석입니다.'},
                    status=status.HTTP_404_NOT_FOUND
                )

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("status", analysis.image_analysis_status)
                detected_count = analysis.uploaded_image.detected_objects.count()
                span.set_attribute("detected_objects_count", detected_count)

            serializer = ImageAnalysisResultSerializer(analysis)
            return Response(serializer.data)


class UploadedImageHistoryView(APIView):
    """
    통합 히스토리 조회 API

    GET /api/v1/uploaded-images/{uploaded_image_id}

    업로드된 이미지에 대한 검출 객체, 매칭 상품, 피팅 정보를 통합 조회합니다.
    DB 조회만 수행하므로 외부 API 호출이 없어 비동기 처리가 필요하지 않습니다.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analyses"],
        summary="통합 히스토리 조회",
        description="업로드된 이미지에 대한 검출 객체, 매칭 상품, 피팅 정보를 통합 조회합니다.",
        parameters=[
            OpenApiParameter("cursor", type=str, description="페이지네이션용 커서"),
            OpenApiParameter("limit", type=int, default=10, description="페이지당 아이템 수")
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'items': { 'type': 'array', 'items': { '$ref': '#/components/schemas/HistoryItem' } },
                    'next_cursor': { 'type': 'string', 'nullable': True }
                }
            }
        }
    )
    def get(self, request, uploaded_image_id):
        """
        통합 히스토리 조회

        Path Params:
            uploaded_image_id: int

        Query Params (optional):
            cursor: string (페이지네이션)
            limit: int (default 10)

        Response 200: {
            items: [{
                detected_object_id, category_name, confidence_score, bbox,
                match: { product_id, product, fitting }
            }]
        }
        """
        # 1. 업로드된 이미지 조회
        try:
            uploaded_image = UploadedImage.objects.get(
                id=uploaded_image_id,
                is_deleted=False
            )
        except UploadedImage.DoesNotExist:
            return Response(
                {'error': '존재하지 않는 이미지입니다.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # 2. 페이지네이션 파라미터
        cursor = request.query_params.get('cursor')
        limit = int(request.query_params.get('limit', 10))

        # 3. 검출된 객체 조회 (관련 데이터 prefetch)
        queryset = DetectedObject.objects.filter(
            uploaded_image=uploaded_image,
            is_deleted=False
        ).prefetch_related(
            'product_mappings',
            'product_mappings__product',
            'product_mappings__product__size_codes',
            'product_mappings__product__size_codes__selections',
        ).order_by('-id')

        # 4. 커서 기반 페이지네이션
        if cursor:
            try:
                cursor_id = int(cursor)
                queryset = queryset.filter(id__lt=cursor_id)
            except ValueError:
                pass

        # 5. limit + 1개 조회 (다음 페이지 존재 여부 확인)
        detected_objects = list(queryset[:limit + 1])

        has_next = len(detected_objects) > limit
        if has_next:
            detected_objects = detected_objects[:limit]

        # 6. 다음 커서 계산
        next_cursor = None
        if has_next and detected_objects:
            next_cursor = str(detected_objects[-1].id)

        # 7. Serializer로 응답 생성
        items = HistoryItemSerializer(detected_objects, many=True).data

        response_data = {
            'items': items,
        }

        # 다음 페이지가 있으면 next_cursor 추가
        if next_cursor:
            response_data['next_cursor'] = next_cursor

        return Response(response_data)