import logging
import uuid

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from services.metrics import IMAGES_UPLOADED_TOTAL
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

logger = logging.getLogger(__name__)


class UploadedImageView(APIView):
    """
    이미지 업로드 API
    
    POST /api/v1/uploaded-images - 이미지 업로드
    GET /api/v1/uploaded-images - 업로드 이력 조회
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        이미지 업로드 (Celery 비동기 처리)

        GCS 업로드를 Celery 워커에서 처리하여 웹 워커 부하 감소.

        Request: multipart/form-data { file: 이미지 }
        Response 201: { uploaded_image_id, uploaded_image_url, created_at }
        """
        import base64

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

            return Response(result, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Failed to upload image: {e}")
            return Response(
                {'error': f'이미지 업로드 중 오류가 발생했습니다: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
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

        # 5. 대상 카테고리 필터링
        target_categories = parsed_query.get('target_categories', available_categories)
        target_objects = detected_objects.filter(object_category__in=target_categories)

        if not target_objects.exists():
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

class AnalysisRefineStatusView(APIView):
    """
    자연어 재분석 상태 조회 API

    GET /api/v1/analyses/{analysis_id}/refine-status?refine_id={refine_id}
    """
    permission_classes = [IsAuthenticated]

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


class UploadedImageHistoryView(APIView):
    """
    통합 히스토리 조회 API

    GET /api/v1/uploaded-images/{uploaded_image_id}

    업로드된 이미지에 대한 검출 객체, 매칭 상품, 피팅 정보를 통합 조회합니다.
    DB 조회만 수행하므로 외부 API 호출이 없어 비동기 처리가 필요하지 않습니다.
    """
    permission_classes = [IsAuthenticated]

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
