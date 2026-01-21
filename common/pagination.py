"""
공통 페이지네이션 유틸리티.

여러 View에서 사용되는 페이지네이션 로직을 통합합니다.
"""

from typing import Optional, Tuple, Any
from urllib.parse import urlparse, parse_qs

from rest_framework.pagination import PageNumberPagination, CursorPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """
    표준 페이지 기반 페이지네이션.

    Usage:
        class MyView(APIView):
            def get(self, request):
                queryset = MyModel.objects.all()
                page, paginator = paginate_queryset(self, queryset, request)
                serializer = MySerializer(page, many=True)
                return paginator.get_paginated_response(serializer.data)
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class StandardCursorPagination(CursorPagination):
    """
    표준 커서 기반 페이지네이션.

    커서 기반 페이지네이션은 대규모 데이터셋에서 더 효율적입니다.
    offset 기반보다 일관된 성능을 제공합니다.

    Usage:
        class MyViewSet(viewsets.ModelViewSet):
            pagination_class = StandardCursorPagination
    """
    ordering = '-created_at'
    page_size = 20
    page_size_query_param = 'limit'

    def get_paginated_response(self, data, key: str = 'items'):
        """
        페이지네이션된 응답 반환.

        Args:
            data: 직렬화된 데이터
            key: 응답 데이터의 키명 (기본값: 'items')

        Returns:
            Response with {key: data, next_cursor: ...}
        """
        next_cursor = self._extract_cursor(self.get_next_link())

        return Response({
            key: data,
            'next_cursor': next_cursor,
        })

    def _extract_cursor(self, url: Optional[str]) -> Optional[str]:
        """URL에서 cursor 파라미터 값 추출."""
        if not url:
            return None
        parsed = urlparse(url)
        return parse_qs(parsed.query).get('cursor', [None])[0]


def paginate_queryset(
    view,
    queryset,
    request,
    paginator_class=StandardPagination
) -> Tuple[Any, Any]:
    """
    표준 페이지네이션 적용.

    Args:
        view: API View 인스턴스
        queryset: 페이지네이션할 QuerySet
        request: HTTP Request
        paginator_class: 사용할 Paginator 클래스

    Returns:
        (page, paginator) 튜플
    """
    paginator = paginator_class()
    page = paginator.paginate_queryset(queryset, request, view=view)
    return page, paginator


class CursorPaginationMixin:
    """
    커서 기반 페이지네이션 믹스인.

    APIView에서 간단한 커서 기반 페이지네이션을 구현할 때 사용합니다.
    ID 기반 커서를 사용하여 효율적인 페이지네이션을 제공합니다.

    Usage:
        class MyView(CursorPaginationMixin, APIView):
            default_limit = 20
            max_limit = 50

            def get(self, request):
                queryset = MyModel.objects.filter(is_deleted=False)
                items, next_cursor = self.paginate_by_id(queryset, request)
                serializer = MySerializer(items, many=True)
                return Response({
                    'items': serializer.data,
                    'next_cursor': next_cursor
                })
    """
    default_limit: int = 20
    max_limit: int = 50

    def paginate_by_id(
        self,
        queryset,
        request,
        cursor_param: str = 'cursor',
        limit_param: str = 'limit'
    ) -> Tuple[list, Optional[str]]:
        """
        ID 기반 커서 페이지네이션 적용.

        Args:
            queryset: 페이지네이션할 QuerySet (id 필드 필요)
            request: HTTP Request
            cursor_param: 커서 파라미터명 (기본값: 'cursor')
            limit_param: 제한 파라미터명 (기본값: 'limit')

        Returns:
            (items, next_cursor) 튜플
        """
        cursor = request.query_params.get(cursor_param)
        limit = min(
            int(request.query_params.get(limit_param, self.default_limit)),
            self.max_limit
        )

        if cursor:
            try:
                queryset = queryset.filter(id__lt=int(cursor))
            except ValueError:
                pass

        # +1개를 가져와서 다음 페이지 존재 여부 확인
        items = list(queryset.order_by('-id')[:limit + 1])

        has_next = len(items) > limit
        if has_next:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_next and items else None

        return items, next_cursor

    def paginate_by_timestamp(
        self,
        queryset,
        request,
        timestamp_field: str = 'created_at',
        cursor_param: str = 'cursor',
        limit_param: str = 'limit'
    ) -> Tuple[list, Optional[str]]:
        """
        타임스탬프 기반 커서 페이지네이션 적용.

        Args:
            queryset: 페이지네이션할 QuerySet
            request: HTTP Request
            timestamp_field: 정렬에 사용할 타임스탬프 필드
            cursor_param: 커서 파라미터명
            limit_param: 제한 파라미터명

        Returns:
            (items, next_cursor) 튜플
        """
        cursor = request.query_params.get(cursor_param)
        limit = min(
            int(request.query_params.get(limit_param, self.default_limit)),
            self.max_limit
        )

        # 타임스탬프 기반 필터링 (ID를 커서로 사용)
        if cursor:
            try:
                queryset = queryset.filter(id__lt=int(cursor))
            except ValueError:
                pass

        # 타임스탬프로 정렬
        items = list(queryset.order_by(f'-{timestamp_field}', '-id')[:limit + 1])

        has_next = len(items) > limit
        if has_next:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_next and items else None

        return items, next_cursor
