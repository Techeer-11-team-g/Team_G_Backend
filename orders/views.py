import logging

from rest_framework import viewsets, status, permissions, mixins
from rest_framework.response import Response
from rest_framework.pagination import CursorPagination
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiResponse

from .models import Order, CartItem
from .serializers import (
    OrderCreateSerializer, OrderSerializer, OrderListSerializer,
    OrderDetailSerializer, OrderCancelSerializer,
    CartItemSerializer, CartItemCreateSerializer
)
from services.metrics import ORDERS_CREATED_TOTAL, CART_ITEMS_TOTAL
from analyses.utils import create_span

logger = logging.getLogger(__name__)

# 트레이서 모듈명
TRACER_NAME = "orders.views"


def _create_span(span_name):
    """트레이싱 span 생성 - analyses.utils.TracingContext 사용."""
    return create_span(TRACER_NAME, span_name)

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

@extend_schema_view(
    list=extend_schema(
        tags=["Orders"],
        summary="주문 내역 조회",
        description="현재 로그인한 사용자의 주문 내역을 조회합니다 (커서 기반 페이지네이션).",
        parameters=[
            OpenApiParameter("cursor", type=str, description="페이지네이션용 커서"),
            OpenApiParameter("limit", type=int, default=20, description="페이지당 주문 수"),
            OpenApiParameter("status", type=str, description="주문 상태 필터링 (paid, preparing, shipping, delivered, canceled)")
        ]
    ),
    create=extend_schema(
        tags=["Orders"],
        summary="주문 생성",
        description="장바구니 항목들을 바탕으로 새로운 주문을 생성합니다.",
        request=OrderCreateSerializer,
        responses={201: OrderSerializer}
    ),
    retrieve=extend_schema(
        tags=["Orders"],
        summary="주문 상세 조회",
        description="특정 주문의 상세 정보를 조회합니다.",
        responses={200: OrderDetailSerializer}
    ),
    partial_update=extend_schema(
        tags=["Orders"],
        summary="주문 취소",
        description="배송 시작 전인 주문을 취소합니다.",
        request=OrderCancelSerializer,
        responses={200: OpenApiResponse(description="취소 성공 응답")}
    )
)
class OrderViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = OrderCursorPagination

    # 1. HTTP 메서드 제한 (PUT 차단) [cite: 48]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    # 2. 각 메서드에 트레이싱 복구 [cite: 16, 47]
    def list(self, request, *args, **kwargs):
        with _create_span("list_orders") as span:
            span.set("user.id", request.user.id)
            return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        with _create_span("create_order") as span:
            span.set("user.id", request.user.id)
            return super().create(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        with _create_span("retrieve_order") as span:
            span.set("user.id", request.user.id)
            return super().retrieve(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        with _create_span("cancel_order") as span:
            span.set("user.id", request.user.id)
            return super().partial_update(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Order.objects.filter(user=self.request.user)

        # status 파라미터가 있으면 필터링(OrderItem의 상태 기준)
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(order_items__order_status=status_param).distinct()
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        elif self.action == 'list':
            return OrderListSerializer
        elif self.action == 'retrieve':
            return OrderDetailSerializer
        elif self.action == 'partial_update':
            return OrderCancelSerializer
        return OrderSerializer

    def perform_create(self, serializer):
        """주문 생성 시 로깅 추가"""
        order = serializer.save()
        ORDERS_CREATED_TOTAL.inc()
        logger.info(
            "주문 생성 완료",
            extra={
                'event': 'order_created',
                'user_id': self.request.user.id,
                'order_id': order.id,
                'total_amount': order.total_amount,
                'item_count': order.order_items.count(),
            }
        )
        return order

class CartItemListCreateView(APIView):
    """
    장바구니 조회 및 추가 API
    """ 
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["Orders"],
        summary="장바구니 조회",
        description="현재 로그인한 사용자의 장바구니 항목들을 조회합니다.",
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'items': { 'type': 'array', 'items': { '$ref': '#/components/schemas/CartItem' } },
                    'total_quantity': { 'type': 'integer' },
                    'total_price': { 'type': 'integer' }
                }
            }
        }
    )

    def get(self, request):
        with _create_span("get_cart") as span:
            span.set("user.id", request.user.id)
            user = request.user
            cart_items = CartItem.objects.filter(user=user).select_related(
                'selected_product__product', 'selected_product__size_code'
            )
            serializer = CartItemSerializer(cart_items, many=True)
            return Response({
                'items': serializer.data,
                'total_quantity': sum(item.quantity for item in cart_items),
                'total_price': sum(item.quantity * item.selected_product.product.selling_price for item in cart_items)
            })

    def post(self, request):
        with _create_span("add_to_cart") as span:
            span.set("user.id", request.user.id)
            serializer = CartItemCreateSerializer(data=request.data, context={'request': request})
            serializer.is_valid(raise_exception=True)
            cart_item = serializer.save()

            CART_ITEMS_TOTAL.labels(action='added').inc()
            logger.info(
                "장바구니 상품 추가",
                extra={
                    'event': 'cart_item_added',
                    'user_id': request.user.id,
                    'cart_item_id': cart_item.id,
                    'product_id': cart_item.selected_product.product_id,
                    'quantity': cart_item.quantity,
                }
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
 
class CartItemDeleteView(APIView):
    """
    장바구니 상품 삭제 API 
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["Orders"],
        summary="장바구니 상품 삭제",
        description="장바구니에서 특정 항목을 삭제(Soft Delete)합니다.",
        responses={204: None}
    )
    def delete(self, request, cart_item_id):
        with _create_span("delete_cart_item") as span:
            span.set("user.id", request.user.id)
            try:
                cart_item = CartItem.objects.get(id=cart_item_id, user=request.user)
                cart_item.delete()  # BaseSoftDeleteModel 작동
                CART_ITEMS_TOTAL.labels(action='removed').inc()
                logger.info(
                    "장바구니 상품 삭제",
                    extra={
                        'event': 'cart_item_removed',
                        'user_id': request.user.id,
                        'cart_item_id': cart_item_id,
                    }
                )
                return Response(status=status.HTTP_204_NO_CONTENT)
            except CartItem.DoesNotExist:
                return Response({'detail': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
