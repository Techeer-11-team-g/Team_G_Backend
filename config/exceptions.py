"""
표준화된 API 예외 클래스.

모든 API 에러 응답을 일관된 형식으로 반환합니다.
기존 코드는 그대로 유지하며, 새 코드 작성 시 이 예외 클래스 사용을 권장합니다.

Response Format:
    {
        "error": "error_code",
        "message": "사용자에게 표시할 메시지"
    }

Usage:
    from config.exceptions import ImageRequiredError, AnalysisNotFoundError

    class MyView(APIView):
        def post(self, request):
            if 'image' not in request.FILES:
                raise ImageRequiredError()
"""

from rest_framework.exceptions import APIException
from rest_framework import status


class BaseAPIException(APIException):
    """
    API 예외 기본 클래스.

    모든 커스텀 API 예외가 상속받습니다.
    일관된 에러 응답 형식을 보장합니다.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'error'
    default_detail = '오류가 발생했습니다.'

    def __init__(self, detail=None, code=None):
        self.detail = {
            'error': code or self.default_code,
            'message': detail or self.default_detail
        }


# =============================================================================
# Validation Errors (400 Bad Request)
# =============================================================================

class ValidationError(BaseAPIException):
    """유효성 검사 에러."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'validation_error'
    default_detail = '입력 데이터가 유효하지 않습니다.'


class ImageRequiredError(ValidationError):
    """이미지 필수 에러."""
    default_code = 'image_required'
    default_detail = '이미지를 업로드해주세요.'


class MessageRequiredError(ValidationError):
    """메시지 필수 에러."""
    default_code = 'message_required'
    default_detail = '메시지를 입력해주세요.'


class InvalidFileTypeError(ValidationError):
    """파일 형식 에러."""
    default_code = 'invalid_file_type'
    default_detail = 'JPG, PNG, WEBP 파일만 업로드 가능합니다.'


class FileTooLargeError(ValidationError):
    """파일 크기 초과 에러."""
    default_code = 'file_too_large'
    default_detail = '파일 크기가 너무 큽니다.'

    def __init__(self, max_size_mb: int = 10):
        super().__init__(f'파일 크기는 {max_size_mb}MB 이하여야 합니다.')


class InvalidParameterError(ValidationError):
    """파라미터 에러."""
    default_code = 'invalid_parameter'
    default_detail = '유효하지 않은 파라미터입니다.'


class CartEmptyError(ValidationError):
    """장바구니 비어있음 에러."""
    default_code = 'cart_empty'
    default_detail = '장바구니가 비어있습니다.'


class InvalidQuantityError(ValidationError):
    """수량 에러."""
    default_code = 'invalid_quantity'
    default_detail = '유효하지 않은 수량입니다.'


class InvalidStatusTypeError(ValidationError):
    """상태 타입 에러."""
    default_code = 'invalid_status_type'
    default_detail = '유효하지 않은 상태 타입입니다.'


# =============================================================================
# Authentication Errors (401 Unauthorized)
# =============================================================================

class UnauthorizedError(BaseAPIException):
    """인증 에러."""
    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = 'unauthorized'
    default_detail = '인증이 필요합니다.'


class InvalidTokenError(UnauthorizedError):
    """토큰 에러."""
    default_code = 'invalid_token'
    default_detail = '유효하지 않은 토큰입니다.'


class TokenExpiredError(UnauthorizedError):
    """토큰 만료 에러."""
    default_code = 'token_expired'
    default_detail = '토큰이 만료되었습니다.'


# =============================================================================
# Permission Errors (403 Forbidden)
# =============================================================================

class ForbiddenError(BaseAPIException):
    """권한 에러."""
    status_code = status.HTTP_403_FORBIDDEN
    default_code = 'forbidden'
    default_detail = '접근 권한이 없습니다.'


class SessionAccessDeniedError(ForbiddenError):
    """세션 접근 거부 에러."""
    default_code = 'session_access_denied'
    default_detail = '해당 세션에 접근할 수 없습니다.'


# =============================================================================
# Not Found Errors (404 Not Found)
# =============================================================================

class ResourceNotFoundError(BaseAPIException):
    """리소스 없음 에러."""
    status_code = status.HTTP_404_NOT_FOUND
    default_code = 'not_found'
    default_detail = '리소스를 찾을 수 없습니다.'


class AnalysisNotFoundError(ResourceNotFoundError):
    """분석 결과 없음 에러."""
    default_code = 'analysis_not_found'
    default_detail = '존재하지 않는 분석입니다.'


class ImageNotFoundError(ResourceNotFoundError):
    """이미지 없음 에러."""
    default_code = 'image_not_found'
    default_detail = '존재하지 않는 이미지입니다.'


class ProductNotFoundError(ResourceNotFoundError):
    """상품 없음 에러."""
    default_code = 'product_not_found'
    default_detail = '존재하지 않는 상품입니다.'


class OrderNotFoundError(ResourceNotFoundError):
    """주문 없음 에러."""
    default_code = 'order_not_found'
    default_detail = '존재하지 않는 주문입니다.'


class SessionNotFoundError(ResourceNotFoundError):
    """세션 없음 에러."""
    default_code = 'session_not_found'
    default_detail = '존재하지 않는 세션입니다.'


class FittingNotFoundError(ResourceNotFoundError):
    """피팅 결과 없음 에러."""
    default_code = 'fitting_not_found'
    default_detail = '존재하지 않는 피팅 결과입니다.'


class UserImageNotFoundError(ResourceNotFoundError):
    """사용자 이미지 없음 에러."""
    default_code = 'user_image_not_found'
    default_detail = '전신 이미지가 등록되어 있지 않습니다.'


class DetectedObjectNotFoundError(ResourceNotFoundError):
    """검출 객체 없음 에러."""
    default_code = 'detected_object_not_found'
    default_detail = '검출된 객체가 없습니다.'


# =============================================================================
# Conflict Errors (409 Conflict)
# =============================================================================

class ConflictError(BaseAPIException):
    """충돌 에러."""
    status_code = status.HTTP_409_CONFLICT
    default_code = 'conflict'
    default_detail = '리소스 충돌이 발생했습니다.'


class DuplicateResourceError(ConflictError):
    """중복 리소스 에러."""
    default_code = 'duplicate_resource'
    default_detail = '이미 존재하는 리소스입니다.'


# =============================================================================
# Server Errors (500 Internal Server Error)
# =============================================================================

class InternalError(BaseAPIException):
    """내부 서버 에러."""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_code = 'internal_error'
    default_detail = '서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'


class UploadError(InternalError):
    """업로드 에러."""
    default_code = 'upload_error'
    default_detail = '업로드 중 오류가 발생했습니다.'


class AnalysisError(InternalError):
    """분석 에러."""
    default_code = 'analysis_error'
    default_detail = '분석 중 오류가 발생했습니다.'


class SearchError(InternalError):
    """검색 에러."""
    default_code = 'search_error'
    default_detail = '검색 중 오류가 발생했습니다.'


class FittingError(InternalError):
    """피팅 에러."""
    default_code = 'fitting_error'
    default_detail = '피팅 처리 중 오류가 발생했습니다.'


class ExternalServiceError(InternalError):
    """외부 서비스 에러."""
    default_code = 'external_service_error'
    default_detail = '외부 서비스 연동 중 오류가 발생했습니다.'


# =============================================================================
# Service Unavailable Errors (503 Service Unavailable)
# =============================================================================

class ServiceUnavailableError(BaseAPIException):
    """서비스 이용 불가 에러."""
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = 'service_unavailable'
    default_detail = '서비스를 일시적으로 이용할 수 없습니다.'


# =============================================================================
# Custom Exception Handler (Optional)
# =============================================================================

def custom_exception_handler(exc, context):
    """
    커스텀 예외 핸들러.

    DRF 기본 예외를 표준 형식으로 변환합니다.
    settings.py의 REST_FRAMEWORK['EXCEPTION_HANDLER']에 등록하여 사용합니다.

    Note:
        기존 에러 처리 로직에 영향을 주지 않으려면 이 핸들러를 등록하지 마세요.
        새 프로젝트나 점진적 마이그레이션 시에만 사용하세요.
    """
    from rest_framework.views import exception_handler

    response = exception_handler(exc, context)

    if response is not None:
        # BaseAPIException이면 이미 표준 형식
        if isinstance(exc, BaseAPIException):
            return response

        # DRF 기본 예외를 표준 형식으로 변환
        error_code = getattr(exc, 'default_code', 'error')
        if hasattr(exc, 'detail'):
            if isinstance(exc.detail, dict):
                message = str(exc.detail)
            elif isinstance(exc.detail, list):
                message = exc.detail[0] if exc.detail else str(exc)
            else:
                message = str(exc.detail)
        else:
            message = str(exc)

        response.data = {
            'error': error_code,
            'message': message
        }

    return response
