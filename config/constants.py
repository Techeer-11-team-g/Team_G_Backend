"""
공통 상수 및 상태 정의.

서비스 전체에서 사용하는 상수들을 중앙 관리합니다.
기존 모델의 상태값은 변경하지 않고, 참조용으로만 사용합니다.

Note:
    기존 모델의 Status 클래스는 그대로 유지합니다.
    이 파일은 새 코드 작성 시 참조용으로 사용합니다.
"""

from enum import Enum
from typing import List, Tuple


class BaseStatus(str, Enum):
    """
    상태 기본 열거형.

    Django choices와 호환됩니다.
    """

    @classmethod
    def choices(cls) -> List[Tuple[str, str]]:
        """Django model choices 형식으로 반환."""
        return [(item.value, item.name.replace('_', ' ').title()) for item in cls]

    @classmethod
    def values(cls) -> List[str]:
        """모든 값 목록 반환."""
        return [item.value for item in cls]

    @classmethod
    def has_value(cls, value: str) -> bool:
        """값 존재 여부 확인."""
        return value in cls.values()


class ProcessingStatus(BaseStatus):
    """
    처리 상태 (분석, 피팅 등).

    기존 모델들의 status 필드와 호환됩니다.
    - ImageAnalysis: PENDING, RUNNING, DONE, FAILED
    - FittingImage: pending, processing, completed, failed
    """
    PENDING = 'PENDING'
    RUNNING = 'RUNNING'
    PROCESSING = 'PROCESSING'
    DONE = 'DONE'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'

    # 소문자 버전 (FittingImage 등과 호환)
    @classmethod
    def lowercase_choices(cls) -> List[Tuple[str, str]]:
        """소문자 choices 반환."""
        return [(item.value.lower(), item.name.replace('_', ' ').title()) for item in cls]


class OrderStatus(BaseStatus):
    """
    주문 상태.

    orders 앱의 Order 모델과 호환됩니다.
    """
    PENDING = 'pending'
    PAID = 'paid'
    PREPARING = 'preparing'
    SHIPPED = 'shipped'
    DELIVERED = 'delivered'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'


class PaymentStatus(BaseStatus):
    """
    결제 상태.
    """
    PENDING = 'pending'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'


# =============================================================================
# Category Constants
# =============================================================================

class FashionCategory(str, Enum):
    """패션 카테고리."""
    TOP = 'top'
    BOTTOM = 'bottom'
    OUTER = 'outer'
    OUTERWEAR = 'outerwear'
    SHOES = 'shoes'
    BAG = 'bag'
    HAT = 'hat'
    SKIRT = 'skirt'
    DRESS = 'dress'
    ACCESSORY = 'accessory'

    @classmethod
    def all_categories(cls) -> List[str]:
        return [item.value for item in cls]


# 카테고리 별칭 (검색 시 사용)
CATEGORY_ALIASES = {
    '상의': ['top'],
    '하의': ['bottom'],
    '아우터': ['outer', 'outerwear'],
    '외투': ['outer', 'outerwear'],
    '신발': ['shoes'],
    '가방': ['bag'],
    '모자': ['hat'],
    '치마': ['skirt'],
    '원피스': ['dress'],
}


# =============================================================================
# Response Type Constants
# =============================================================================

class ResponseType(str, Enum):
    """에이전트 응답 타입."""
    SEARCH_RESULTS = 'search_results'
    NO_RESULTS = 'no_results'
    FITTING_PENDING = 'fitting_pending'
    FITTING_RESULT = 'fitting_result'
    BATCH_FITTING_PENDING = 'batch_fitting_pending'
    CART_ADDED = 'cart_added'
    CART_LIST = 'cart_list'
    CART_EMPTY = 'cart_empty'
    ORDER_CREATED = 'order_created'
    SIZE_RECOMMENDATION = 'size_recommendation'
    ASK_SELECTION = 'ask_selection'
    ASK_SIZE = 'ask_size'
    ASK_BODY_INFO = 'ask_body_info'
    ASK_USER_IMAGE = 'ask_user_image'
    ASK_SEARCH_FIRST = 'ask_search_first'
    GENERAL = 'general'
    GREETING = 'greeting'
    HELP = 'help'
    ERROR = 'error'
    ANALYSIS_PENDING = 'analysis_pending'


class IntentType(str, Enum):
    """사용자 의도 타입."""
    SEARCH = 'search'
    FITTING = 'fitting'
    COMMERCE = 'commerce'
    GENERAL = 'general'


class SubIntentType(str, Enum):
    """세부 의도 타입."""
    # Search
    NEW_SEARCH = 'new_search'
    REFINE = 'refine'
    SIMILAR = 'similar'
    CROSS_RECOMMEND = 'cross_recommend'

    # Fitting
    SINGLE_FIT = 'single_fit'
    COMPARE_FIT = 'compare_fit'
    BATCH_FIT = 'batch_fit'

    # Commerce
    ADD_CART = 'add_cart'
    VIEW_CART = 'view_cart'
    REMOVE_CART = 'remove_cart'
    SIZE_RECOMMEND = 'size_recommend'
    CHECKOUT = 'checkout'
    ORDER_STATUS = 'order_status'
    CANCEL_ORDER = 'cancel_order'

    # General
    GREETING = 'greeting'
    HELP = 'help'
    FEEDBACK = 'feedback'


# =============================================================================
# API Constants
# =============================================================================

# 페이지네이션 기본값
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# 파일 업로드 제한
MAX_IMAGE_SIZE_MB = 10
ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']

# Redis TTL
REDIS_TTL_SESSION = 3600 * 24  # 24시간
REDIS_TTL_ANALYSIS = 3600 * 2  # 2시간
REDIS_TTL_CACHE = 3600  # 1시간


# =============================================================================
# Search Constants
# =============================================================================

class SearchConfig:
    """검색 설정."""
    K = 30  # k-NN 검색 결과 수
    SEARCH_K = 100  # 검색 후보 수
    RERANK_TOP_K = 15  # 리랭킹 대상 수
    FINAL_RESULTS = 5  # 최종 결과 수


class ImageConfig:
    """이미지 처리 설정."""
    MAX_FILE_SIZE_MB = 10
    BBOX_PADDING_RATIO = 0.1
    JPEG_QUALITY = 95
    ALLOWED_CONTENT_TYPES = ['image/jpeg', 'image/png', 'image/webp']
