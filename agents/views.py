"""
AI 패션 어시스턴트 - API Views
채팅 엔드포인트 및 상태 조회
"""

import logging

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiParameter

from agents.orchestrator import MainOrchestrator
from agents.serializers import (
    ChatRequestSerializer,
    ChatResponseSerializer,
    StatusCheckRequestSerializer,
)
from services.metrics import CHAT_SESSION_OPERATIONS_TOTAL

logger = logging.getLogger(__name__)


class ChatView(APIView):
    """
    채팅 API 엔드포인트

    POST /api/v1/chat
    - 텍스트 메시지 및/또는 이미지 처리
    - 의도 분류 → 서브 에이전트 라우팅 → 응답 생성
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]

    @extend_schema(
        tags=["Chat"],
        summary="AI 채팅 메시지 전송",
        description="""
AI 패션 어시스턴트와 대화합니다.

**지원 기능:**
- 텍스트 메시지: 상품 검색, 장바구니 관리, 피팅 요청 등
- 이미지 첨부: 이미지 기반 유사 상품 검색
- 복합 요청: 이미지 + 텍스트로 세부 조건 지정

**Intent 분류:**
- search: 상품 검색 (텍스트/이미지)
- fitting: 가상 피팅 요청
- commerce: 장바구니, 주문 관련
- general: 인사, 도움말 등
        """,
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'message': {
                        'type': 'string',
                        'description': '사용자 메시지 (예: "검정 자켓 찾아줘", "1번 입어볼래")'
                    },
                    'session_id': {
                        'type': 'string',
                        'description': '세션 ID (없으면 새 세션 생성)'
                    },
                    'image': {
                        'type': 'string',
                        'format': 'binary',
                        'description': '검색할 이미지 파일 (선택)'
                    }
                }
            }
        },
        responses={
            200: ChatResponseSerializer,
            400: OpenApiResponse(description="메시지 또는 이미지가 필요합니다"),
            500: OpenApiResponse(description="서버 오류")
        },
        examples=[
            OpenApiExample(
                "텍스트 검색 요청",
                value={
                    "message": "검정색 자켓 추천해줘",
                    "session_id": "abc123"
                },
                request_only=True,
            ),
            OpenApiExample(
                "피팅 요청",
                value={
                    "message": "1번 입어볼래",
                    "session_id": "abc123"
                },
                request_only=True,
            ),
            OpenApiExample(
                "장바구니 추가",
                value={
                    "message": "2번 M사이즈로 장바구니에 담아줘",
                    "session_id": "abc123"
                },
                request_only=True,
            ),
        ]
    )
    def post(self, request):
        """채팅 메시지 처리"""
        try:
            # 요청 파싱
            message = request.data.get('message', '')
            session_id = request.data.get('session_id')
            analysis_id = request.data.get('analysis_id')  # 이전 분석 ID (필터 변경용)
            image_file = request.FILES.get('image')

            # 이미지 바이트 추출
            image_bytes = None
            if image_file:
                image_bytes = image_file.read()

            # 메시지와 이미지 모두 없으면 에러
            if not message and not image_bytes:
                return Response(
                    {
                        "error": "message_required",
                        "detail": "메시지 또는 이미지를 입력해주세요."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 오케스트레이터 초기화
            orchestrator = MainOrchestrator(
                user_id=request.user.id,
                session_id=session_id,
                analysis_id=analysis_id  # 이전 분석 컨텍스트 유지용
            )

            # 메시지 처리 (async → sync 변환)
            response = self._process_message(orchestrator, message, image_bytes)

            logger.info(
                "Chat message processed",
                extra={
                    'event': 'chat_processed',
                    'user_id': request.user.id,
                    'session_id': response.get('session_id'),
                    'response_type': response.get('response', {}).get('type'),
                }
            )

            return Response(response, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(
                f"Chat API error: {e}",
                exc_info=True,
                extra={
                    'event': 'chat_error',
                    'user_id': request.user.id if request.user else None,
                }
            )
            return Response(
                {
                    "error": "internal_error",
                    "detail": "처리 중 오류가 발생했습니다."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _process_message(self, orchestrator, message, image_bytes):
        """메시지 처리"""
        return orchestrator.process_message(message, image_bytes)


class ChatStatusView(APIView):
    """
    상태 확인 API

    POST /api/v1/chat/status
    - 분석 또는 피팅 상태 확인
    - 완료 시 결과 반환
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Chat"],
        summary="분석/피팅 상태 폴링",
        description="""
이미지 분석 또는 가상 피팅 작업의 상태를 확인합니다.

**상태 값:**
- PENDING: 대기 중
- RUNNING: 처리 중
- DONE: 완료
- FAILED: 실패

**폴링 권장 간격:** 1-2초
        """,
        request=StatusCheckRequestSerializer,
        responses={
            200: ChatResponseSerializer,
            400: OpenApiResponse(description="잘못된 요청"),
        },
        examples=[
            OpenApiExample(
                "분석 상태 확인",
                value={
                    "type": "analysis",
                    "id": 123,
                    "session_id": "abc123"
                },
                request_only=True,
            ),
            OpenApiExample(
                "피팅 상태 확인",
                value={
                    "type": "fitting",
                    "id": 456,
                    "session_id": "abc123"
                },
                request_only=True,
            ),
        ]
    )
    def post(self, request):
        """상태 확인"""
        serializer = StatusCheckRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        check_type = serializer.validated_data['type']
        check_id = serializer.validated_data['id']
        session_id = request.data.get('session_id')

        orchestrator = MainOrchestrator(
            user_id=request.user.id,
            session_id=session_id
        )

        if check_type == 'analysis':
            response = orchestrator.check_analysis_status(check_id)
        else:  # fitting
            response = orchestrator.check_fitting_status(check_id)

        return Response(
            {
                "session_id": orchestrator.session_id,
                "response": response,
            },
            status=status.HTTP_200_OK
        )


class ChatSessionView(APIView):
    """
    세션 관리 API

    GET /api/v1/chat/sessions - 세션 목록 (최근)
    DELETE /api/v1/chat/sessions/{session_id} - 세션 삭제
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Chat"],
        summary="채팅 세션 조회",
        description="""
특정 채팅 세션의 정보와 대화 이력을 조회합니다.

**반환 정보:**
- 세션 메타데이터 (생성일, 마지막 활동일)
- 대화 이력 (최근 20턴)
- 컨텍스트 정보 (검색 결과, 장바구니 등)
        """,
        parameters=[
            OpenApiParameter(
                name="session_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="조회할 세션 ID",
                required=False
            )
        ],
        responses={
            200: OpenApiResponse(description="세션 정보"),
            403: OpenApiResponse(description="권한 없음"),
            404: OpenApiResponse(description="세션을 찾을 수 없음"),
        }
    )
    def get(self, request, session_id=None):
        """세션 조회"""
        from services import get_redis_service

        redis = get_redis_service()

        if session_id:
            # 특정 세션 조회
            key = f"agent:session:{session_id}"
            data = redis.get(key)

            if not data:
                return Response(
                    {"error": "session_not_found"},
                    status=status.HTTP_404_NOT_FOUND
                )

            import json
            session_data = json.loads(data)

            # 소유권 확인
            if session_data.get('user_id') != request.user.id:
                return Response(
                    {"error": "forbidden"},
                    status=status.HTTP_403_FORBIDDEN
                )

            # 대화 이력 조회
            turns_key = f"agent:session:{session_id}:turns"
            turns = redis.lrange(turns_key, 0, -1)
            session_data['turns'] = [json.loads(t) for t in turns] if turns else []

            return Response(session_data, status=status.HTTP_200_OK)

        else:
            # 세션 목록은 현재 지원하지 않음 (Redis 패턴 스캔 필요)
            return Response(
                {"message": "Use session_id to get specific session"},
                status=status.HTTP_200_OK
            )

    @extend_schema(
        tags=["Chat"],
        summary="채팅 세션 삭제",
        description="채팅 세션과 관련 대화 이력을 삭제합니다.",
        parameters=[
            OpenApiParameter(
                name="session_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="삭제할 세션 ID",
                required=True
            )
        ],
        responses={
            204: OpenApiResponse(description="삭제 완료"),
            403: OpenApiResponse(description="권한 없음"),
        }
    )
    def delete(self, request, session_id):
        """세션 삭제"""
        from services import get_redis_service

        redis = get_redis_service()

        # 세션 존재 및 소유권 확인
        key = f"agent:session:{session_id}"
        data = redis.get(key)

        if data:
            import json
            session_data = json.loads(data)

            if session_data.get('user_id') != request.user.id:
                return Response(
                    {"error": "forbidden"},
                    status=status.HTTP_403_FORBIDDEN
                )

        # 삭제
        redis.delete(key)
        redis.delete(f"agent:session:{session_id}:turns")
        CHAT_SESSION_OPERATIONS_TOTAL.labels(operation='delete').inc()

        return Response(status=status.HTTP_204_NO_CONTENT)
