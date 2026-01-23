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
    extract_style_tags_task,
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

    def _validate_file(self, file):
        """
        파일 유효성 검사.

        Returns:
            None if valid, Response with error if invalid
        """
        from .constants import ImageConfig

        if not file:
            return Response(
                {'error': {'file': ['파일이 필요합니다.']}},
                status=status.HTTP_400_BAD_REQUEST
            )

        if file.size > ImageConfig.MAX_FILE_SIZE_MB * 1024 * 1024:
            return Response(
                {'error': {'file': [f'파일 크기는 {ImageConfig.MAX_FILE_SIZE_MB}MB 이하여야 합니다.']}},
                status=status.HTTP_400_BAD_REQUEST
            )

        if file.content_type not in ImageConfig.ALLOWED_CONTENT_TYPES:
            return Response(
                {'error': {'file': ['JPG, PNG, WEBP 파일만 업로드 가능합니다.']}},
                status=status.HTTP_400_BAD_REQUEST
            )

        return None

    def _process_auto_analyze(self, image_b64, file, user_id):
        """
        auto_analyze=True 처리: GCS 업로드와 분석을 병렬로 시작.

        Returns:
            Response with analysis info
        """
        from users.models import User
        from .models import ImageAnalysis

        user = None
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                pass

        uploaded_image = UploadedImage.objects.create(
            user=user,
            uploaded_image_url='pending',
        )
        uploaded_image_id = uploaded_image.id

        analysis = ImageAnalysis.objects.create(
            uploaded_image=uploaded_image,
            image_analysis_status=ImageAnalysis.Status.PENDING,
        )

        # 트레이스 컨텍스트 전파를 위한 헤더 생성
        from opentelemetry.propagate import inject
        trace_headers = {}
        inject(trace_headers)

        # 세 태스크를 병렬 실행 (멀티스레드 워커가 동시 처리)
        upload_image_to_gcs_task.apply_async(
            args=[image_b64, file.name, file.content_type, user_id],
            kwargs={'uploaded_image_id': uploaded_image_id},
            headers=trace_headers,
        )
        process_image_analysis.apply_async(
            args=[str(analysis.id), None],
            kwargs={'user_id': user_id, 'image_b64': image_b64},
            headers=trace_headers,
        )
        extract_style_tags_task.apply_async(
            args=[uploaded_image_id, image_b64],
            headers=trace_headers,
        )

        logger.info(
            "이미지 업로드 및 분석 시작 (병렬 모드)",
            extra={
                'event': 'image_upload_with_analysis',
                'user_id': user_id,
                'uploaded_image_id': uploaded_image_id,
                'analysis_id': str(analysis.id),
                'file_name': file.name,
                'file_size': file.size,
            }
        )
        IMAGES_UPLOADED_TOTAL.inc()

        return Response({
            'uploaded_image_id': uploaded_image_id,
            'uploaded_image_url': 'pending',
            'created_at': uploaded_image.created_at.isoformat(),
            'auto_analyze': True,
            'analysis_id': analysis.id,
            'analysis_status': 'PENDING',
            'polling': {
                'status_url': f'/api/v1/analyses/{analysis.id}/status',
                'result_url': f'/api/v1/analyses/{analysis.id}',
            }
        }, status=status.HTTP_201_CREATED)

    def _process_upload_only(self, image_b64, file, user_id):
        """
        auto_analyze=False 처리: GCS 업로드만.

        Returns:
            Response with upload result
        """
        result = upload_image_to_gcs_task.apply_async(
            args=[image_b64, file.name, file.content_type, user_id],
        ).get(timeout=60)

        logger.info(
            "이미지 업로드 완료",
            extra={
                'event': 'image_uploaded',
                'user_id': user_id,
                'uploaded_image_id': result.get('uploaded_image_id'),
                'file_name': file.name,
                'file_size': file.size,
            }
        )
        IMAGES_UPLOADED_TOTAL.inc()

        return Response(result, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Analyses"],
        summary="이미지 업로드",
        description="분석할 이미지를 업로드합니다 (최대 10MB). auto_analyze=true 시 업로드와 분석을 동시에 시작합니다.",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'file': {
                        'type': 'string',
                        'format': 'binary',
                        'description': '분석할 이미지 파일 (JPG, PNG, WEBP)'
                    },
                    'auto_analyze': {
                        'type': 'boolean',
                        'description': 'true 시 업로드와 동시에 분석 시작 (GCS 다운로드 생략으로 더 빠름)'
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
        auto_analyze=true 시 GCS 업로드와 분석을 병렬로 시작
        """
        import base64

        with create_span(TRACER_NAME, "api_upload_image") as ctx:
            ctx.set("http.method", "POST")
            ctx.set("api.endpoint", "/api/v1/uploaded-images")

            # 1. 파일 유효성 검사
            file = request.FILES.get('file')
            validation_error = self._validate_file(file)
            if validation_error:
                return validation_error

            # auto_analyze 옵션 확인
            auto_analyze = request.data.get('auto_analyze', '').lower() in ('true', '1', 'yes')

            ctx.set("file.name", file.name)
            ctx.set("file.size", file.size)
            ctx.set("file.content_type", file.content_type)
            ctx.set("auto_analyze", auto_analyze)

            # 2. 파일을 Base64로 인코딩 (Celery 전달용)
            file_bytes = file.read()
            image_b64 = base64.b64encode(file_bytes).decode('utf-8')

            # 3. 사용자 ID 가져오기
            user_id = request.user.id if request.user.is_authenticated else None

            # 4. Celery 태스크 실행
            # CeleryInstrumentor가 자동으로 trace context 전파 (propagate_headers=True)
            try:
                if auto_analyze:
                    response = self._process_auto_analyze(image_b64, file, user_id)
                    ctx.set("parallel_mode", True)
                    ctx.set("status", "success")
                    return response
                else:
                    response = self._process_upload_only(image_b64, file, user_id)
                    ctx.set("status", "success")
                    return response

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
        ).prefetch_related('analyses')  # N+1 방지: analysis_id 조회용

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

        # 4. LangChain 쿼리 파싱 (v2: 다중 요청 + 대화 히스토리 지원)
        available_categories = list(
            detected_objects.values_list('object_category', flat=True).distinct()
        )
        parsed_result = self._parse_query(query, available_categories, analysis_id)

        # v2 다중 요청 처리
        understood_intent = None
        clarification_needed = False
        clarification_question = None

        if 'requests' in parsed_result:
            # v2 응답: 다중 요청
            requests_list = parsed_result.get('requests', [])
            understood_intent = parsed_result.get('understood_intent')
            clarification_needed = parsed_result.get('clarification_needed', False)
            clarification_question = parsed_result.get('clarification_question')

            # 확인이 필요한 경우 먼저 응답
            if clarification_needed and clarification_question:
                return Response({
                    'clarification_needed': True,
                    'clarification_question': clarification_question,
                    'understood_intent': understood_intent,
                }, status=status.HTTP_200_OK)
        else:
            # v1 응답: 단일 요청
            requests_list = [parsed_result]

        # 5. 각 요청별로 대상 객체 수집 (다중 요청 병렬 처리)
        all_subtasks = []
        refine_id = str(uuid.uuid4())

        from opentelemetry.propagate import inject
        refine_headers = {}
        inject(refine_headers)

        for req in requests_list:
            # 해당 요청의 대상 카테고리 필터링
            target_objects = self._filter_by_categories(
                detected_objects, req.get('target_categories', [])
            )

            for obj_id in target_objects.values_list('id', flat=True):
                all_subtasks.append(
                    refine_single_object.s(
                        refine_id=refine_id,
                        detected_object_id=obj_id,
                        parsed_query=req,  # 개별 요청의 필터 적용
                    ).set(headers=refine_headers)
                )

        # 6. Celery Group으로 병렬 처리
        try:
            if all_subtasks:
                job = group(all_subtasks)
                results = job.apply_async().get(timeout=300)
                logger.info(
                    "자연어 재분석 완료",
                    extra={
                        'event': 'refine_completed',
                        'analysis_id': str(analysis_id),
                        'refine_id': refine_id,
                        'query': query,
                        'requests_count': len(requests_list),
                        'objects_processed': len(results),
                        'understood_intent': understood_intent,
                    }
                )

        except Exception as e:
            logger.error(f"Failed to process refine tasks: {e}")
            return Response(
                {'error': f'재분석 처리 중 오류가 발생했습니다: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 7. 최신 데이터로 응답 반환 (understood_intent 포함)
        analysis.refresh_from_db()
        response_serializer = AnalysisRefineResponseSerializer(analysis)
        response_data = response_serializer.data

        # 사용자 피드백용 의도 요약 추가
        if understood_intent:
            response_data['understood_intent'] = understood_intent

        return Response(response_data)

    def _get_target_objects(self, analysis, detected_object_id):
        """대상 객체 조회."""
        if detected_object_id:
            return analysis.uploaded_image.detected_objects.filter(
                id=detected_object_id, is_deleted=False
            )
        return analysis.uploaded_image.detected_objects.filter(is_deleted=False)

    def _parse_query(self, query, available_categories, analysis_id=None):
        """
        LangChain 쿼리 파싱.

        v2 기능:
        - Function Calling으로 구조화된 파싱
        - 다중 요청 지원
        - 대화 히스토리 문맥 유지
        """
        try:
            # CeleryInstrumentor가 자동으로 trace context 전파
            parsed_query = parse_refine_query_task.apply_async(
                args=[query, available_categories],
                kwargs={'analysis_id': analysis_id},  # 대화 문맥용
            ).get(timeout=30)

            # v2 다중 요청 처리
            if 'requests' in parsed_query:
                logger.info(f"V2 parsed: {len(parsed_query['requests'])} requests")
                logger.info(f"Understood: {parsed_query.get('understood_intent')}")
            else:
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

        # 명시적으로 카테고리를 지정했으면 해당 결과만 반환 (폴백 제거)
        # 매칭되는 객체가 없으면 빈 결과 반환
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
                image_url = uploaded_image.uploaded_image_url

            # Celery task 트리거 (트레이스 컨텍스트 수동 전파)
            from opentelemetry.propagate import inject
            trace_headers = {}
            inject(trace_headers)

            try:
                process_image_analysis.apply_async(
                    args=[str(analysis.id), image_url],
                    kwargs={'user_id': request.user.id if request.user.is_authenticated else None},
                    headers=trace_headers,
                )
                logger.info(
                    "이미지 분석 시작",
                    extra={
                        'event': 'analysis_started',
                        'user_id': request.user.id if request.user.is_authenticated else None,
                        'analysis_id': str(analysis.id),
                        'uploaded_image_id': analysis.uploaded_image.id,
                    }
                )
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


class FeedView(APIView):
    """
    공개 피드 API (Pinterest 스타일)

    GET /api/v1/feed - 모든 사용자의 공개된 이미지 분석 조회
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Feed"],
        summary="공개 피드 조회",
        description="모든 사용자의 공개된 이미지 분석 결과를 Pinterest 스타일로 조회합니다.",
        parameters=[
            OpenApiParameter("cursor", type=str, description="페이지네이션용 커서"),
            OpenApiParameter("limit", type=int, default=20, description="페이지당 아이템 수"),
            OpenApiParameter("category", type=str, description="카테고리 필터 (shoes, top, bottom 등)"),
            OpenApiParameter("style", type=str, description="스타일 태그 필터 (amekaji, casual, street 등)"),
        ],
        responses={200: OpenApiResponse(description="피드 목록")}
    )
    def get(self, request):
        """공개 피드 조회"""
        from django.db.models import Q
        from .serializers import FeedItemSerializer

        cursor = request.query_params.get('cursor')
        limit = min(int(request.query_params.get('limit', 20)), 50)  # 최대 50개
        category = request.query_params.get('category')
        style = request.query_params.get('style')

        # 공개 + 분석 완료된 이미지만 조회
        queryset = UploadedImage.objects.filter(
            is_public=True,
            is_deleted=False,
            analyses__image_analysis_status='DONE',
            analyses__is_deleted=False,
        ).select_related('user').prefetch_related(
            'analyses',
            'detected_objects',
            'detected_objects__product_mappings',
            'detected_objects__product_mappings__product',
        ).distinct().order_by('-created_at')

        # 카테고리 필터
        if category:
            queryset = queryset.filter(
                detected_objects__object_category=category,
                detected_objects__is_deleted=False
            ).distinct()

        # 스타일 태그 필터 (style_tag1 또는 style_tag2에 있으면 매칭)
        if style:
            queryset = queryset.filter(
                Q(style_tag1=style) | Q(style_tag2=style)
            )

        # 커서 기반 페이지네이션
        if cursor:
            try:
                queryset = queryset.filter(id__lt=int(cursor))
            except ValueError:
                pass

        images = list(queryset[:limit + 1])

        has_next = len(images) > limit
        if has_next:
            images = images[:limit]

        next_cursor = str(images[-1].id) if has_next and images else None

        # detected_objects를 미리 로드하여 serializer에 전달
        for img in images:
            img._prefetched_detected_objects = [
                do for do in img.detected_objects.all() if not do.is_deleted
            ]
            img._prefetched_analysis = next(
                (a for a in img.analyses.all() if not a.is_deleted), None
            )

        serializer = FeedItemSerializer(images, many=True)

        response_data = {'items': serializer.data}
        if next_cursor:
            response_data['next_cursor'] = next_cursor

        return Response(response_data)


class FeedStylesView(APIView):
    """
    피드 스타일 태그 목록 API

    GET /api/v1/feed/styles - 필터 버튼용 스타일 태그 목록
    """
    permission_classes = [IsAuthenticated]

    # 스타일 태그 정의 (버튼 표시용)
    STYLE_TAGS = [
        {"value": "amekaji", "label": "아메카지"},
        {"value": "casual", "label": "캐주얼"},
        {"value": "street", "label": "스트릿"},
        {"value": "minimal", "label": "미니멀"},
        {"value": "formal", "label": "포멀"},
        {"value": "sporty", "label": "스포티"},
        {"value": "vintage", "label": "빈티지"},
        {"value": "cityboy", "label": "시티보이"},
        {"value": "preppy", "label": "프레피"},
        {"value": "workwear", "label": "워크웨어"},
        {"value": "bohemian", "label": "보헤미안"},
        {"value": "feminine", "label": "페미닌"},
        {"value": "gothic", "label": "고딕"},
        {"value": "normcore", "label": "놈코어"},
    ]

    @extend_schema(
        tags=["Feed"],
        summary="스타일 태그 목록 조회",
        description="피드 필터 버튼용 스타일 태그 목록을 반환합니다.",
        responses={200: OpenApiResponse(description="스타일 태그 목록")}
    )
    def get(self, request):
        """스타일 태그 목록 반환"""
        return Response({
            "styles": self.STYLE_TAGS
        })


class MyHistoryView(APIView):
    """
    내 히스토리 API

    GET /api/v1/my-history - 본인의 이미지 분석 히스토리 조회
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Feed"],
        summary="내 히스토리 조회",
        description="본인이 업로드한 이미지 분석 히스토리를 조회합니다.",
        parameters=[
            OpenApiParameter("cursor", type=str, description="페이지네이션용 커서"),
            OpenApiParameter("limit", type=int, default=20, description="페이지당 아이템 수"),
        ],
        responses={200: OpenApiResponse(description="히스토리 목록")}
    )
    def get(self, request):
        """내 히스토리 조회"""
        from .serializers import FeedItemSerializer

        cursor = request.query_params.get('cursor')
        limit = min(int(request.query_params.get('limit', 20)), 50)

        # 본인의 이미지만 조회 (삭제되지 않은 것)
        queryset = UploadedImage.objects.filter(
            user=request.user,
            is_deleted=False,
        ).select_related('user').prefetch_related(
            'analyses',
            'detected_objects',
            'detected_objects__product_mappings',
            'detected_objects__product_mappings__product',
        ).order_by('-created_at')

        # 커서 기반 페이지네이션
        if cursor:
            try:
                queryset = queryset.filter(id__lt=int(cursor))
            except ValueError:
                pass

        images = list(queryset[:limit + 1])

        has_next = len(images) > limit
        if has_next:
            images = images[:limit]

        next_cursor = str(images[-1].id) if has_next and images else None

        # detected_objects를 미리 로드
        for img in images:
            img._prefetched_detected_objects = [
                do for do in img.detected_objects.all() if not do.is_deleted
            ]
            img._prefetched_analysis = next(
                (a for a in img.analyses.all() if not a.is_deleted), None
            )

        serializer = FeedItemSerializer(images, many=True)

        response_data = {'items': serializer.data}
        if next_cursor:
            response_data['next_cursor'] = next_cursor

        return Response(response_data)


class TogglePublicView(APIView):
    """
    공개/비공개 토글 API

    PATCH /api/v1/uploaded-images/{id}/visibility - 공개 상태 토글
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Feed"],
        summary="공개/비공개 토글",
        description="업로드된 이미지의 공개 상태를 변경합니다.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "is_public": {"type": "boolean", "description": "공개 여부"}
                }
            }
        },
        responses={200: OpenApiResponse(description="변경 완료")}
    )
    def patch(self, request, uploaded_image_id):
        """공개 상태 토글"""
        try:
            image = UploadedImage.objects.get(
                id=uploaded_image_id,
                user=request.user,
                is_deleted=False
            )
        except UploadedImage.DoesNotExist:
            return Response(
                {'error': '이미지를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # is_public 값 변경
        is_public = request.data.get('is_public')
        if is_public is not None:
            image.is_public = is_public
        else:
            # 값이 없으면 토글
            image.is_public = not image.is_public

        image.save(update_fields=['is_public', 'updated_at'])

        return Response({
            'id': image.id,
            'is_public': image.is_public,
            'message': '공개로 설정되었습니다.' if image.is_public else '비공개로 설정되었습니다.'
        })
