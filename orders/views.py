from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework import mixins
from rest_framework.pagination import CursorPagination
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiResponse
from django.contrib.auth import get_user_model
from .models import Order, CartItem

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

    def create(self, request, *args, **kwargs):
        """
        주문 생성 API
        """
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        
        # Response(201 Created) body construction handled by serializer.to_representation
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
        user = request.user
        cart_items = CartItem.objects.filter(
            user=user,
            is_deleted=False
        ).select_related('selected_product__product', 'selected_product__size_code')

        serializer = CartItemSerializer(cart_items, many=True)

        # 총 수량, 총 가격 계산
        total_quantity = sum(item.quantity for item in cart_items)
        total_price = sum(
            item.quantity * item.selected_product.product.selling_price
            for item in cart_items
        )

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
        serializer = CartItemCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        cart_item = serializer.save()
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
        return Response(status=status.HTTP_204_NO_CONTENT)