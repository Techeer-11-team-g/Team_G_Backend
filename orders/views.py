from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework import mixins
from rest_framework.pagination import CursorPagination
from .models import Order
from .serializers import OrderCreateSerializer, OrderSerializer, OrderListSerializer, OrderDetailSerializer, OrderCancelSerializer

class OrderCursorPagination(CursorPagination):
    ordering = '-created_at'
    page_size_query_param = 'limit'

    def get_paginated_response(self, data):
        next_url = self.get_next_link()
        next_cursor = None 
        # 다음 페이지가 있는 경우 URL에서 cursor 값만 추출 
        if next_url:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(next_url)
            # cursor 파라미터 값 추출 
            next_cursor = parse_qs(parsed.query).get('cursor', [None])[0]

        return Response({
            'orders': data,
            'next_cursor': next_cursor,
        })

class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = OrderCursorPagination # 위에서 만든 클래스 연결 

    def get_queryset(self):
        queryset = Order.objects.filter(user=self.request.user, is_deleted=False)

        # status 파라미터가 있으면 필터링(OrderItem의 상태 기준)
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(order_items__order_status=status_param).distinct()
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        elif self.action == 'list': # list 액션 추가 
            return OrderListSerializer
        elif self.action == 'retrieve':
            return OrderDetailSerializer 
        elif self.action == 'partial_update':
            return OrderCancelSerializer
        return OrderSerializer

    def create(self, request, *args, **kwargs):
        """
        주문 생성 API
        """
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        
        # Response(201 Created) body construction handled by serializer.to_representation
        return Response(serializer.data, status=status.HTTP_201_CREATED) 