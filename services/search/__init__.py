"""
OpenSearch 검색 모듈.

분리된 검색 기능을 제공합니다:
- client: 기본 클라이언트 및 인덱스 작업
- strategies: 다양한 검색 전략
- utils: 상수 및 유틸리티 함수
"""

from .client import (
    OpenSearchClient,
    get_client,
    get_opensearch_client,
)
from .strategies import SearchStrategies
from .utils import (
    KNN_INDEX_SETTINGS,
    RELATED_CATEGORIES,
    CONFLICTING_COLORS,
    COLOR_KEYWORDS,
    ITEM_TYPE_KEYWORDS,
    get_related_categories,
    get_conflicting_colors,
    get_color_keywords,
    get_item_type_config,
    parse_search_result,
)


class OpenSearchService(OpenSearchClient, SearchStrategies):
    """
    OpenSearch 통합 서비스 클래스.

    OpenSearchClient와 SearchStrategies를 상속하여
    기존 코드와의 호환성을 유지합니다.

    하위 호환성을 위해 기존 opensearch_client.py의 모든 기능을 제공합니다.
    """

    # 기존 코드 호환성을 위한 클래스 변수
    KNN_INDEX_SETTINGS = KNN_INDEX_SETTINGS
    RELATED_CATEGORIES = RELATED_CATEGORIES
    CONFLICTING_COLORS = CONFLICTING_COLORS
    COLOR_KEYWORDS = COLOR_KEYWORDS
    ITEM_TYPE_KEYWORDS = ITEM_TYPE_KEYWORDS

    def __init__(self):
        OpenSearchClient.__init__(self)
        SearchStrategies.__init__(self)

    def _get_conflicting_colors(self, color: str) -> list:
        """기존 메서드명 호환성 유지."""
        return get_conflicting_colors(color)


__all__ = [
    # Main service class
    'OpenSearchService',
    # Client
    'OpenSearchClient',
    'get_client',
    'get_opensearch_client',
    # Strategies
    'SearchStrategies',
    # Utils
    'KNN_INDEX_SETTINGS',
    'RELATED_CATEGORIES',
    'CONFLICTING_COLORS',
    'COLOR_KEYWORDS',
    'ITEM_TYPE_KEYWORDS',
    'get_related_categories',
    'get_conflicting_colors',
    'get_color_keywords',
    'get_item_type_config',
    'parse_search_result',
]
