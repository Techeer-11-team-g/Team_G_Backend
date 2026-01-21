"""
Request/Response Logging Middleware.

모든 API 요청과 응답을 자동으로 로깅합니다.
"""

import logging
import time
import json

logger = logging.getLogger('config.middleware')


class RequestLoggingMiddleware:
    """
    HTTP 요청/응답 자동 로깅 미들웨어.

    로깅 내용:
    - 요청: method, path, user_id, client_ip
    - 응답: status_code, duration_ms
    """

    # 로깅에서 제외할 경로 (헬스체크, 메트릭스 등)
    EXCLUDE_PATHS = [
        '/health/',
        '/metrics',
        '/favicon.ico',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 제외 경로 체크
        if self._should_skip(request.path):
            return self.get_response(request)

        # 요청 시작 시간
        start_time = time.time()

        # 요청 로깅
        self._log_request(request)

        # 뷰 처리
        response = self.get_response(request)

        # 응답 로깅
        duration_ms = (time.time() - start_time) * 1000
        self._log_response(request, response, duration_ms)

        return response

    def _should_skip(self, path: str) -> bool:
        """로깅 제외 경로인지 확인"""
        return any(path.startswith(exclude) for exclude in self.EXCLUDE_PATHS)

    def _get_client_ip(self, request) -> str:
        """클라이언트 IP 주소 추출"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')

    def _get_user_id(self, request) -> str:
        """사용자 ID 추출 (인증된 경우)"""
        if hasattr(request, 'user') and request.user.is_authenticated:
            return str(request.user.id)
        return 'anonymous'

    def _log_request(self, request):
        """요청 로깅"""
        logger.info(
            "API Request",
            extra={
                'event': 'api_request',
                'method': request.method,
                'path': request.path,
                'user_id': self._get_user_id(request),
                'client_ip': self._get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:100],
            }
        )

    def _log_response(self, request, response, duration_ms: float):
        """응답 로깅"""
        # 상태 코드에 따라 로그 레벨 결정
        status_code = response.status_code
        log_level = logging.INFO

        if status_code >= 500:
            log_level = logging.ERROR
        elif status_code >= 400:
            log_level = logging.WARNING

        logger.log(
            log_level,
            "API Response",
            extra={
                'event': 'api_response',
                'method': request.method,
                'path': request.path,
                'status_code': status_code,
                'duration_ms': round(duration_ms, 2),
                'user_id': self._get_user_id(request),
            }
        )
