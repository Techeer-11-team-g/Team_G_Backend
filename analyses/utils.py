"""
analyses 앱 공통 유틸리티 모듈.

여러 파일에서 사용되는 공통 함수들을 중앙화합니다:
- 카테고리 정규화
- bbox 처리
- 트레이싱 유틸리티
- 속성 필터링
"""

from contextlib import nullcontext
from functools import lru_cache
from typing import Optional

from .constants import (
    CATEGORY_MAPPING,
    CATEGORY_ALIASES,
    CATEGORY_DESCRIPTIONS,
    ATTRIBUTE_FILTER_RULES,
)


# =============================================================================
# 카테고리 유틸리티
# =============================================================================

def normalize_category(category: str) -> str:
    """
    Vision API 카테고리를 OpenSearch 카테고리로 변환.

    Args:
        category: Vision API에서 반환된 카테고리 (예: 'bottom', 'outerwear')

    Returns:
        정규화된 카테고리 (예: 'pants', 'outer')
    """
    return CATEGORY_MAPPING.get(category.lower(), category)


def expand_category_aliases(categories: list[str]) -> set[str]:
    """
    카테고리 목록을 alias 포함하여 확장.

    LangChain 출력값을 DB에서 검색 가능한 카테고리로 확장합니다.

    Args:
        categories: LangChain에서 파싱된 카테고리 목록

    Returns:
        확장된 카테고리 집합 (예: ['pants'] → {'pants', 'bottom', '하의', '바지'})
    """
    expanded = set()
    for cat in categories:
        cat_lower = cat.lower()
        if cat_lower in CATEGORY_ALIASES:
            expanded.update(CATEGORY_ALIASES[cat_lower])
        else:
            expanded.add(cat)
    return expanded


def get_category_description(category: str) -> str:
    """
    FashionCLIP 텍스트 임베딩용 카테고리 설명 반환.

    Args:
        category: 카테고리명

    Returns:
        FashionCLIP에 최적화된 설명 (예: 'pants' → 'pants trousers')
    """
    return CATEGORY_DESCRIPTIONS.get(category, category)


# =============================================================================
# Bbox 유틸리티
# =============================================================================

def normalize_bbox(bbox: dict, width: int, height: int) -> dict:
    """
    픽셀 bbox를 0-1 범위로 정규화.

    Args:
        bbox: 픽셀 좌표 bbox {'x_min', 'y_min', 'x_max', 'y_max'}
        width: 이미지 너비
        height: 이미지 높이

    Returns:
        정규화된 bbox {'x1', 'y1', 'x2', 'y2'} (0-1 범위)
    """
    return {
        'x1': bbox.get('x_min', 0) / width if width > 0 else 0,
        'y1': bbox.get('y_min', 0) / height if height > 0 else 0,
        'x2': bbox.get('x_max', 0) / width if width > 0 else 0,
        'y2': bbox.get('y_max', 0) / height if height > 0 else 0,
    }


def format_bbox_for_api(obj) -> dict:
    """
    DetectedObject의 bbox를 API 응답 형식으로 변환.

    Args:
        obj: DetectedObject 인스턴스 (bbox_x1, bbox_x2, bbox_y1, bbox_y2 속성 필요)

    Returns:
        API 응답용 bbox dict {'x1', 'x2', 'y1', 'y2'}
    """
    return {
        'x1': round(obj.bbox_x1, 2),
        'x2': round(obj.bbox_x2, 2),
        'y1': round(obj.bbox_y1, 2),
        'y2': round(obj.bbox_y2, 2),
    }


# =============================================================================
# 트레이싱 유틸리티
# =============================================================================

@lru_cache(maxsize=16)
def get_tracer(module_name: str):
    """
    OpenTelemetry tracer를 가져옴 (캐싱 적용).

    Args:
        module_name: 모듈 식별자 (예: 'analyses.views')

    Returns:
        Tracer 인스턴스 또는 None (OTel 미설치 시)
    """
    try:
        from opentelemetry import trace
        return trace.get_tracer(module_name)
    except ImportError:
        return None


def create_span(tracer_name: str, span_name: str):
    """
    트레이싱 span 컨텍스트 매니저 생성.

    Args:
        tracer_name: tracer 모듈명
        span_name: span 이름

    Returns:
        span 컨텍스트 매니저 (OTel 미설치 시 nullcontext)
    """
    tracer = get_tracer(tracer_name)
    if tracer:
        return tracer.start_as_current_span(span_name)
    return nullcontext()


class TracingContext:
    """
    안전한 span 속성 설정을 위한 컨텍스트 매니저.

    Usage:
        with TracingContext("module", "span_name") as ctx:
            ctx.set("key", "value")  # 안전하게 속성 설정
    """

    def __init__(self, tracer_name: str, span_name: str):
        self.tracer = get_tracer(tracer_name)
        self.span_name = span_name
        self.span = None

    def __enter__(self):
        if self.tracer:
            self.span = self.tracer.start_as_current_span(self.span_name).__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            self.span.__exit__(exc_type, exc_val, exc_tb)
        return False

    def set(self, key: str, value) -> None:
        """span 속성을 안전하게 설정."""
        if self.span and hasattr(self.span, 'set_attribute'):
            self.span.set_attribute(key, value)


# =============================================================================
# 속성 필터링 유틸리티
# =============================================================================

def apply_attribute_filters(results: list, parsed_query: dict) -> list:
    """
    검색 결과에 속성 필터를 적용.

    Args:
        results: OpenSearch 검색 결과 리스트
        parsed_query: LangChain 파싱 결과 (필터 조건 포함)

    Returns:
        필터링된 결과 리스트
    """
    filtered = []
    for result in results:
        if _matches_all_filters(result, parsed_query):
            filtered.append(result)
    return filtered


def _matches_all_filters(result: dict, parsed_query: dict) -> bool:
    """모든 필터 조건을 만족하는지 확인."""
    for filter_key, result_key, match_type in ATTRIBUTE_FILTER_RULES:
        filter_value = parsed_query.get(filter_key)
        if filter_value and not _check_filter(result, result_key, filter_value, match_type):
            return False
    return True


def _check_filter(result: dict, result_key: str, filter_value: str, match_type: str) -> bool:
    """개별 필터 조건 확인."""
    result_value = result.get(result_key)

    if result_value is None:
        return False

    filter_lower = filter_value.lower()

    if match_type == 'list_contains':
        # 리스트에 값 포함 여부
        if isinstance(result_value, str):
            result_value = [result_value]
        return filter_lower in [v.lower() for v in result_value]

    elif match_type == 'contains':
        # 문자열 포함 여부
        return filter_lower in str(result_value).lower()

    elif match_type == 'exact':
        # 정확히 일치
        return filter_lower == str(result_value).lower()

    return False


# =============================================================================
# 텍스트 임베딩 설명 생성
# =============================================================================

def build_fashion_description(parsed_query: dict, category: str) -> str:
    """
    FashionCLIP용 상세 설명 생성.

    Args:
        parsed_query: LangChain 파싱 결과
        category: 객체 카테고리

    Returns:
        FashionCLIP에 최적화된 검색 텍스트
    """
    parts = []

    # 속성 추출기 정의 (키, 변환 함수)
    attribute_extractors = [
        ('color_filter', lambda v: v),
        ('material_filter', lambda v: v),
        ('pattern_filter', lambda v: v if v != 'solid' else None),
        ('sleeve_length', lambda v: v.replace('_', ' ')),
        ('pants_length', lambda v: 'short' if v == 'shorts' else v),
        ('outer_length', lambda v: v),
        ('style_vibe', lambda v: v),
    ]

    for key, transform in attribute_extractors:
        value = parsed_query.get(key)
        if value:
            transformed = transform(value)
            if transformed:
                parts.append(transformed)

    # 스타일 키워드 추가
    style_keywords = parsed_query.get('style_keywords') or []
    parts.extend(style_keywords)

    # 검색 키워드 추가
    search_keywords = parsed_query.get('search_keywords')
    if search_keywords:
        parts.append(search_keywords)

    # 카테고리 설명 추가
    parts.append(get_category_description(category))

    return ' '.join(parts)


# =============================================================================
# Product 생성 유틸리티
# =============================================================================

def get_or_create_product_from_search(
    product_id: str,
    search_result: dict,
    default_category: str = 'unknown'
):
    """
    검색 결과로부터 Product 조회 또는 생성.

    Args:
        product_id: 무신사 상품 ID
        search_result: OpenSearch 검색 결과 dict
        default_category: 기본 카테고리

    Returns:
        Product 인스턴스
    """
    from products.models import Product

    # 1. 기존 Product 검색
    product = Product.objects.filter(
        product_url__endswith=f'/{product_id}'
    ).first()

    # 2. 없으면 생성
    if not product:
        product, _ = Product.objects.update_or_create(
            product_url=f'https://www.musinsa.com/app/goods/{product_id}',
            defaults={
                'brand_name': search_result.get('brand', 'Unknown') or 'Unknown',
                'product_name': search_result.get('name', 'Unknown') or 'Unknown',
                'category': search_result.get('category', default_category),
                'selling_price': int(search_result.get('price', 0) or 0),
                'product_image_url': search_result.get('image_url', '') or '',
            }
        )

    return product
