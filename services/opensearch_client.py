"""
OpenSearch client configuration.

Note: 이 파일은 하위 호환성을 위해 유지됩니다.
새로운 코드는 services.search 모듈을 직접 사용하세요.

Example:
    from services.search import OpenSearchService, get_client
"""

# Re-export from the new search module for backward compatibility
from services.search import (
    OpenSearchService,
    OpenSearchClient,
    get_client,
    get_opensearch_client,
    SearchStrategies,
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

__all__ = [
    'OpenSearchService',
    'OpenSearchClient',
    'get_client',
    'get_opensearch_client',
    'SearchStrategies',
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
