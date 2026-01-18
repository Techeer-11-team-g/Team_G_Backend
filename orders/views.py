import logging
from contextlib import nullcontext

from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework import mixins
from rest_framework.pagination import CursorPagination
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiResponse
from django.contrib.auth import get_user_model
from .models import Order, CartItem

from services.metrics import ORDERS_CREATED_TOTAL, CART_ITEMS_TOTAL

logger = logging.getLogger(__name__)


def _get_tracer():
    """Get tracer lazily to ensure TracerProvider is initialized."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("orders.views")
    except ImportError:
        return None


def _create_span(name: str):
    """Create a span if tracer is available."""
    tracer = _get_tracer()
    if tracer:
        return tracer.start_as_current_span(name)
    return nullcontext()


User = get_user_model()
from .serializers import (
    OrderCreateSerializer, OrderSerializer, OrderListSerializer,
    OrderDetailSerializer, OrderCancelSerializer,
    CartItemSerializer, CartItemCreateSerializer
)

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

    def list(self, request, *args, **kwargs):
        """주문 목록 조회 API with tracing"""
        with _create_span("api_order_list") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)

            # Step 1: Fetch orders from database
            with _create_span("1_fetch_orders_db") as db_span:
                queryset = self.filter_queryset(self.get_queryset())
                if db_span and hasattr(db_span, 'set_attribute'):
                    db_span.set_attribute("service", "mysql")

            # Step 2: Paginate results
            with _create_span("2_paginate_orders") as page_span:
                page = self.paginate_queryset(queryset)
                if page is not None:
                    serializer = self.get_serializer(page, many=True)
                    if page_span and hasattr(page_span, 'set_attribute'):
                        page_span.set_attribute("page_size", len(page))
                    return self.get_paginated_response(serializer.data)

            # Step 3: Serialize all results (no pagination)
            with _create_span("3_serialize_orders") as ser_span:
                serializer = self.get_serializer(queryset, many=True)
                if ser_span and hasattr(ser_span, 'set_attribute'):
                    ser_span.set_attribute("order_count", len(serializer.data))

            return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """
        주문 생성 API
        """
        with _create_span("api_order_create") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)

            # Step 1: Validate request
            with _create_span("1_validate_order_request") as v_span:
                serializer = self.get_serializer(data=request.data, context={'request': request})
                serializer.is_valid(raise_exception=True)
                if v_span and hasattr(v_span, 'set_attribute'):
                    v_span.set_attribute("validation", "passed")

            # Step 2: Create order in database
            with _create_span("2_create_order_db") as db_span:
                order = serializer.save()
                if db_span and hasattr(db_span, 'set_attribute'):
                    db_span.set_attribute("order.id", order.id)
                    db_span.set_attribute("service", "mysql")

            ORDERS_CREATED_TOTAL.inc()
            logger.info(f"Order created: {order.id} by user {request.user.id}")

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("order.id", order.id)

            return Response(serializer.data, status=status.HTTP_201_CREATED)


class CartItemListCreateView(APIView):
    """
    장바구니 조회 및 추가 API
    GET /api/v1/cart-items - 장바구니 조회
    POST /api/v1/cart-items - 장바구니 추가
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
        """장바구니 조회"""
        with _create_span("api_cart_list") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)

            # Step 1: Fetch cart items from database
            with _create_span("1_fetch_cart_items_db") as db_span:
                user = request.user
                cart_items = CartItem.objects.filter(
                    user=user,
                    is_deleted=False
                ).select_related('selected_product__product', 'selected_product__size_code')
                cart_items = list(cart_items)
                if db_span and hasattr(db_span, 'set_attribute'):
                    db_span.set_attribute("service", "mysql")
                    db_span.set_attribute("item_count", len(cart_items))

            # Step 2: Calculate totals and serialize
            with _create_span("2_calculate_totals") as calc_span:
                serializer = CartItemSerializer(cart_items, many=True)
                total_quantity = sum(item.quantity for item in cart_items)
                total_price = sum(
                    item.quantity * item.selected_product.product.selling_price
                    for item in cart_items
                )
                if calc_span and hasattr(calc_span, 'set_attribute'):
                    calc_span.set_attribute("total_quantity", total_quantity)
                    calc_span.set_attribute("total_price", total_price)

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("cart.item_count", len(cart_items))
                span.set_attribute("cart.total_quantity", total_quantity)

            return Response({
                'items': serializer.data,
                'total_quantity': total_quantity,
                'total_price': total_price
            })

    @extend_schema(
        tags=["Orders"],
        summary="장바구니 추가",
        description="특정 상품(사이즈 포함)을 장바구니에 추가합니다. 이미 있으면 수량이 증가합니다.",
        request=CartItemCreateSerializer,
        responses={201: CartItemCreateSerializer}
    )
    def post(self, request):
        """장바구니 추가"""
        with _create_span("api_cart_add") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)

            serializer = CartItemCreateSerializer(data=request.data, context={'request': request})
            serializer.is_valid(raise_exception=True)
            cart_item = serializer.save()

            CART_ITEMS_TOTAL.labels(action='added').inc()
            logger.info(f"Cart item added: {cart_item.id} by user {request.user.id}")

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("cart_item.id", cart_item.id)

            return Response(serializer.data, status=status.HTTP_201_CREATED)


class CartItemDeleteView(APIView):
    """
    장바구니 상품 삭제 API
    DELETE /api/v1/cart-items/{cart_item_id}
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["Orders"],
        summary="장바구니 상품 삭제",
        description="장바구니에서 특정 항목을 삭제(Soft Delete)합니다.",
        responses={244: None}
    )
    def delete(self, request, cart_item_id):
        """장바구니 상품 삭제 (Soft Delete)"""
        with _create_span("api_cart_delete") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("user.id", request.user.id)
                span.set_attribute("cart_item.id", cart_item_id)

            user = request.user
            try:
                cart_item = CartItem.objects.get(
                    id=cart_item_id,
                    user=user,
                    is_deleted=False
                )
            except CartItem.DoesNotExist:
                return Response(
                    {'detail': '해당 장바구니 항목을 찾을 수 없습니다.'},
                    status=status.HTTP_404_NOT_FOUND
                )

            cart_item.is_deleted = True
            cart_item.save()

            CART_ITEMS_TOTAL.labels(action='removed').inc()
            logger.info(f"Cart item removed: {cart_item_id} by user {request.user.id}")

            return Response(status=status.HTTP_204_NO_CONTENT)