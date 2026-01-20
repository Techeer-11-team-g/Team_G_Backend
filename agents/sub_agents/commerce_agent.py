"""
AI 패션 어시스턴트 - 커머스 에이전트
기존 Cart/Order 시스템을 활용한 구매 처리
"""

import re
import logging
from typing import Dict, Any, Optional, List

from django.db import transaction

from agents.response_builder import ResponseBuilder
from config.tracing import traced, get_tracer
from products.models import Product

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


class CommerceAgent:
    """
    커머스 에이전트 - 기존 Cart/Order 모델 활용

    핵심 연동 포인트:
    - CartItem 모델: 장바구니
    - Order, OrderItem 모델: 주문
    - SelectedProduct 모델: 상품+사이즈 조합
    - SizeCode 모델: 사이즈 정보
    """

    def __init__(self, user_id: int):
        self.user_id = user_id

    def _resolve_product(self, product_info: Dict[str, Any]) -> Optional[Product]:
        """
        검색 결과의 상품 정보를 로컬 Product로 변환

        검색 결과는 외부 API(Musinsa)의 product_id를 사용하지만,
        SelectedProduct/CartItem은 로컬 Product FK를 참조하므로 변환이 필요.
        """
        product_url = product_info.get('product_url')
        if not product_url:
            return None

        return Product.objects.filter(
            product_url=product_url,
            is_deleted=False
        ).first()

    @traced("commerce_agent.handle")
    def handle(
        self,
        sub_intent: str,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """커머스 요청 처리"""
        try:
            if sub_intent == 'add_cart':
                return self.add_to_cart(message, context)

            elif sub_intent == 'direct_purchase':
                return self.direct_purchase(message, context)

            elif sub_intent == 'view_cart':
                return self.view_cart()

            elif sub_intent == 'remove_cart':
                return self.remove_from_cart(message, context)

            elif sub_intent == 'update_cart':
                return self.update_cart(message, context)

            elif sub_intent == 'size_recommend':
                return self.recommend_size(message, context)

            elif sub_intent == 'checkout':
                return self.checkout(context)

            elif sub_intent == 'order_status':
                return self.order_status(message)

            elif sub_intent == 'cancel_order':
                return self.cancel_order(message)

            else:
                return self.view_cart()

        except Exception as e:
            logger.error(f"CommerceAgent error: {e}", exc_info=True)
            return ResponseBuilder.error(
                "commerce_error",
                "처리 중 문제가 발생했어요. 다시 시도해주세요."
            )

    @traced("commerce_agent.add_to_cart")
    def add_to_cart(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        장바구니 추가 - 기존 CartItem 모델 활용

        1. 상품 선택 (컨텍스트 또는 인덱스)
        2. 사이즈 파싱/선택
        3. SelectedProduct 생성
        4. CartItem 생성
        """
        from orders.models import CartItem
        from analyses.models import SelectedProduct
        from products.models import SizeCode

        # pending_action 확인 (사이즈 선택 대기 중일 경우)
        pending = context.get('pending_action')
        if pending and pending.get('type') == 'select_size_for_cart':
            # pending_action에서 상품 정보 가져오기
            selected = pending.get('product')
            product_id = pending.get('local_product_id')

            if not selected or not product_id:
                # pending data가 불완전하면 초기화
                context.pop('pending_action', None)
            else:
                # 사이즈 파싱 시도
                size = self._parse_size(message)
                if size:
                    # pending_action 완료, 클리어
                    context.pop('pending_action', None)
                    # 아래 로직으로 진행 (product_id, selected 설정됨)
                    return self._complete_add_to_cart(
                        selected, product_id, size, message, context
                    )

        # 1. 상품 선택 - 인덱스 참조가 있으면 검색 결과에서 선택!
        refs = context.get('intent_result', {}).get('references', {})
        indices = refs.get('indices', [])
        products = context.get('search_results', [])

        selected = None

        # 인덱스 참조가 있으면 검색 결과에서 선택 (우선순위!)
        if indices and products and indices[0] <= len(products):
            selected = products[indices[0] - 1]
        elif not indices:
            # 인덱스 없으면 이전 선택 상품 사용
            selected = context.get('selected_product')

        if not selected:
            if not products:
                return ResponseBuilder.ask_search_first()
            elif len(products) == 1:
                selected = products[0]
            else:
                return ResponseBuilder.ask_selection(
                    "어떤 상품을 담을까요?",
                    products
                )

        # 2. 로컬 Product 조회 (외부 product_id → 로컬 Product)
        local_product = self._resolve_product(selected)
        if not local_product:
            return ResponseBuilder.error(
                "product_not_found",
                "해당 상품 정보를 찾을 수 없어요. 다른 상품을 선택해주세요."
            )

        product_id = local_product.id  # 로컬 Product ID 사용

        # 3. 사이즈 파싱
        size = self._parse_size(message)
        commerce_params = context.get('intent_result', {}).get('commerce_params', {})
        if not size:
            size = commerce_params.get('size')

        # 사이즈가 없으면 요청
        if not size:
            sizes_data = selected.get('sizes', [])
            # sizes가 dict 리스트인 경우 size 값만 추출
            if sizes_data and isinstance(sizes_data[0], dict):
                sizes = [s.get('size') for s in sizes_data if s.get('size')]
            else:
                sizes = sizes_data

            if not sizes:
                # SizeCode에서 조회
                sizes = list(SizeCode.objects.filter(
                    product_id=product_id,
                    is_deleted=False
                ).values_list('size_value', flat=True))

            if sizes:
                # 컨텍스트에 pending_action 설정 (다음 메시지에서 사이즈 선택 처리)
                context['pending_action'] = {
                    'type': 'select_size_for_cart',
                    'product': selected,
                    'local_product_id': product_id,
                    'available_sizes': sizes
                }
                context['selected_product'] = selected
                return ResponseBuilder.ask_size(
                    f"{selected.get('product_name', '상품')}의 사이즈를 선택해주세요:",
                    sizes
                )
            else:
                size = 'FREE'

        # 4. 수량 파싱 및 검증
        quantity = self._parse_quantity(message)
        if not quantity:
            quantity = commerce_params.get('quantity', 1)
        # 수량은 최소 1, 최대 99
        quantity = max(1, min(99, quantity))

        # 5. SizeCode 조회
        size_code = SizeCode.objects.filter(
            product_id=product_id,
            size_value=size,
            is_deleted=False
        ).first()

        # 6. SelectedProduct 생성/조회
        selected_product, _ = SelectedProduct.objects.get_or_create(
            product_id=product_id,
            size_code=size_code,
            defaults={'selected_product_inventory': 0}
        )

        # 7. CartItem 생성/업데이트
        cart_item, created = CartItem.objects.get_or_create(
            user_id=self.user_id,
            selected_product=selected_product,
            is_deleted=False,
            defaults={'quantity': quantity}
        )
        if not created:
            cart_item.quantity += quantity
            cart_item.save()

        # 컨텍스트 업데이트
        context['selected_product'] = selected
        context['selected_size'] = size

        return ResponseBuilder.cart_added(selected, size, cart_item.quantity)

    @traced("commerce_agent.direct_purchase")
    def direct_purchase(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        바로 구매 - 사이즈 선택 후 즉시 결제

        플로우: 상품 선택 → 사이즈 선택 → 장바구니 담기 → 바로 결제
        """
        from orders.models import CartItem
        from analyses.models import SelectedProduct
        from products.models import SizeCode

        # pending_action 확인 (사이즈 선택 대기 중일 경우)
        pending = context.get('pending_action')
        if pending and pending.get('type') == 'select_size_for_direct_purchase':
            selected = pending.get('product')
            product_id = pending.get('local_product_id')

            if not selected or not product_id:
                context.pop('pending_action', None)
            else:
                size = self._parse_size(message)
                if size:
                    context.pop('pending_action', None)
                    # 장바구니에 담고 바로 결제
                    return self._complete_direct_purchase(
                        selected, product_id, size, message, context
                    )

        # 1. 상품 선택 - 인덱스 참조가 있으면 검색 결과에서 선택!
        refs = context.get('intent_result', {}).get('references', {})
        indices = refs.get('indices', [])
        products = context.get('search_results', [])

        selected = None

        # 인덱스 참조가 있으면 검색 결과에서 선택 (우선순위!)
        if indices and products and indices[0] <= len(products):
            selected = products[indices[0] - 1]
        elif not indices:
            # 인덱스 없으면 이전 선택 상품 사용
            selected = context.get('selected_product')

        if not selected:
            if not products:
                return ResponseBuilder.ask_search_first()
            elif len(products) == 1:
                selected = products[0]
            else:
                return ResponseBuilder.ask_selection(
                    "어떤 상품을 구매하시겠어요?",
                    products
                )

        # 2. 로컬 Product 조회
        local_product = self._resolve_product(selected)
        if not local_product:
            return ResponseBuilder.error(
                "product_not_found",
                "해당 상품 정보를 찾을 수 없어요. 다른 상품을 선택해주세요."
            )

        product_id = local_product.id

        # 3. 사이즈 파싱
        size = self._parse_size(message)
        commerce_params = context.get('intent_result', {}).get('commerce_params', {})
        if not size:
            size = commerce_params.get('size')

        # 사이즈가 없으면 요청
        if not size:
            sizes_data = selected.get('sizes', [])
            # sizes가 dict 리스트인 경우 size 값만 추출
            if sizes_data and isinstance(sizes_data[0], dict):
                sizes = [s.get('size') for s in sizes_data if s.get('size')]
            else:
                sizes = sizes_data

            if not sizes:
                sizes = list(SizeCode.objects.filter(
                    product_id=product_id,
                    is_deleted=False
                ).values_list('size_value', flat=True))

            if sizes:
                # direct_purchase용 pending_action 설정
                context['pending_action'] = {
                    'type': 'select_size_for_direct_purchase',
                    'product': selected,
                    'local_product_id': product_id,
                    'available_sizes': sizes
                }
                context['selected_product'] = selected
                return ResponseBuilder.ask_size(
                    f"{selected.get('product_name', '상품')}의 사이즈를 선택해주세요:",
                    sizes
                )
            else:
                size = 'FREE'

        # 사이즈 있으면 바로 구매 진행
        return self._complete_direct_purchase(
            selected, product_id, size, message, context
        )

    def _complete_direct_purchase(
        self,
        selected: Dict[str, Any],
        product_id: int,
        size: str,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """바로 구매 완료 - 장바구니 담기 + 즉시 결제"""
        from orders.models import CartItem, Order, OrderItem
        from analyses.models import SelectedProduct
        from products.models import SizeCode, Product
        from users.models import User

        # 1. SizeCode 조회
        size_code = SizeCode.objects.filter(
            product_id=product_id,
            size_value=size,
            is_deleted=False
        ).first()

        # 2. SelectedProduct 생성/조회
        selected_product, _ = SelectedProduct.objects.get_or_create(
            product_id=product_id,
            size_code=size_code,
            defaults={'selected_product_inventory': 0}
        )

        # 3. Product 정보 조회
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            return ResponseBuilder.error(
                "product_not_found",
                "상품 정보를 찾을 수 없어요."
            )

        # 4. 사용자 정보
        try:
            user = User.objects.get(id=self.user_id)
        except User.DoesNotExist:
            return ResponseBuilder.error(
                "user_not_found",
                "사용자 정보를 찾을 수 없어요."
            )

        # 5. 바로 주문 생성 (장바구니 스킵)
        quantity = 1
        total_price = product.selling_price * quantity

        with transaction.atomic():
            order = Order.objects.create(
                user=user,
                total_price=total_price,
                delivery_address=user.address or '배송지를 입력해주세요'
            )

            OrderItem.objects.create(
                order=order,
                selected_product=selected_product,
                purchased_quantity=quantity,
                price_at_order=product.selling_price,
                order_status='PENDING'
            )

        # 컨텍스트 정리
        context.pop('pending_action', None)
        context.pop('selected_product', None)

        return {
            "text": f"🎉 주문이 완료되었어요!\n\n"
                    f"📦 {selected.get('product_name', product.product_name)}\n"
                    f"📐 사이즈: {size}\n"
                    f"💰 결제 금액: ₩{total_price:,}\n\n"
                    f"주문번호: #{order.id}",
            "type": "order_created",
            "data": {
                "order_id": order.id,
                "product": selected,
                "size": size,
                "total_price": total_price
            },
            "suggestions": [
                {"label": "주문 내역 보기", "action": "order_status"},
                {"label": "쇼핑 계속하기", "action": "search"}
            ]
        }

    @traced("commerce_agent.view_cart")
    def view_cart(self) -> Dict[str, Any]:
        """장바구니 조회"""
        from orders.models import CartItem

        items = CartItem.objects.filter(
            user_id=self.user_id,
            is_deleted=False
        ).select_related(
            'selected_product__product',
            'selected_product__size_code'
        )

        cart_items = []
        total_price = 0

        for item in items:
            product = item.selected_product.product
            size_code = item.selected_product.size_code

            item_data = {
                'cart_item_id': item.id,
                'product': {
                    'product_id': product.id,
                    'brand_name': product.brand_name,
                    'product_name': product.product_name,
                    'selling_price': product.selling_price,
                    'image_url': product.product_image_url,
                },
                'size': size_code.size_value if size_code else 'FREE',
                'quantity': item.quantity,
            }
            cart_items.append(item_data)
            total_price += product.selling_price * item.quantity

        return ResponseBuilder.cart_list(cart_items, total_price)

    def remove_from_cart(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """장바구니에서 제거"""
        from orders.models import CartItem

        # 인덱스 또는 상품 참조 확인
        refs = context.get('intent_result', {}).get('references', {})
        indices = refs.get('indices', [])

        items_list = list(CartItem.objects.filter(
            user_id=self.user_id,
            is_deleted=False
        ).select_related('selected_product__product'))

        if not items_list:
            return ResponseBuilder.error(
                "empty_cart",
                "장바구니가 비어있어요."
            )

        if indices:
            # 인덱스로 삭제
            for idx in indices:
                if idx <= len(items_list):
                    items_list[idx - 1].is_deleted = True
                    items_list[idx - 1].save()

            return {
                "text": "장바구니에서 삭제했어요.",
                "type": "cart_removed",
                "data": {},
                "suggestions": [
                    {"label": "장바구니 보기", "action": "view_cart"}
                ]
            }
        else:
            # 전체 삭제 확인
            if "전부" in message or "다" in message or "비워" in message:
                CartItem.objects.filter(
                    user_id=self.user_id,
                    is_deleted=False
                ).update(is_deleted=True)
                return {
                    "text": "장바구니를 비웠어요.",
                    "type": "cart_cleared",
                    "data": {},
                    "suggestions": [
                        {"label": "상품 검색", "action": "search"}
                    ]
                }

        # 어떤 것을 삭제할지 확인
        cart_items = [
            {
                'index': i,
                'product_name': item.selected_product.product.product_name
            }
            for i, item in enumerate(items_list, 1)
        ]

        return {
            "text": "어떤 상품을 삭제할까요?\n" +
                    "\n".join([f"{c['index']}. {c['product_name']}" for c in cart_items]),
            "type": "ask_remove",
            "data": {"items": cart_items},
            "suggestions": [
                {"label": "전부 삭제", "action": "clear_cart"}
            ]
        }

    def update_cart(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """장바구니 수량 변경"""
        from orders.models import CartItem

        quantity = self._parse_quantity(message)
        if not quantity:
            return ResponseBuilder.error(
                "invalid_quantity",
                "수량을 알려주세요. (예: 3개로)"
            )

        refs = context.get('intent_result', {}).get('references', {})
        indices = refs.get('indices', [])

        items = list(CartItem.objects.filter(
            user_id=self.user_id,
            is_deleted=False
        ))

        if not items:
            return ResponseBuilder.error(
                "empty_cart",
                "장바구니가 비어있어요."
            )

        if indices and indices[0] <= len(items):
            item = items[indices[0] - 1]
            item.quantity = quantity
            item.save()

            return {
                "text": f"수량을 {quantity}개로 변경했어요.",
                "type": "cart_updated",
                "data": {},
                "suggestions": [
                    {"label": "장바구니 보기", "action": "view_cart"}
                ]
            }

        return self.view_cart()

    def recommend_size(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """사이즈 추천"""
        # 신체 정보 파싱
        height, weight = self._parse_body_info(message)
        commerce_params = context.get('intent_result', {}).get('commerce_params', {})
        body_info = commerce_params.get('body_info', {})

        if not height:
            height = body_info.get('height')
        if not weight:
            weight = body_info.get('weight')

        # 상품 확인
        selected = context.get('selected_product')
        if not selected:
            products = context.get('search_results', [])
            if products:
                selected = products[0]
            else:
                return ResponseBuilder.error(
                    "no_product",
                    "어떤 상품의 사이즈를 추천해드릴까요? 먼저 상품을 찾아주세요."
                )

        # 신체 정보가 없으면 요청
        if not height or not weight:
            return ResponseBuilder.ask_body_info()

        # 사이즈 추천 로직
        product_id = selected.get('product_id') or selected.get('id')

        from products.models import SizeCode

        sizes = list(SizeCode.objects.filter(
            product_id=product_id,
            is_deleted=False
        ).values_list('size_value', flat=True))

        recommended = self._calculate_size(height, weight, selected.get('category', ''))
        confidence = 85  # 기본 신뢰도

        # 컨텍스트 업데이트
        context['selected_product'] = selected
        context['recommended_size'] = recommended

        return ResponseBuilder.size_recommendation(
            recommended,
            sizes,
            confidence,
            selected
        )

    @traced("commerce_agent.checkout")
    def checkout(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """주문 생성 - 기존 Order 모델 활용"""
        from orders.models import CartItem, Order, OrderItem
        from users.models import User

        # 장바구니 확인
        cart_items = list(CartItem.objects.filter(
            user_id=self.user_id,
            is_deleted=False
        ).select_related('selected_product__product'))

        if not cart_items:
            return ResponseBuilder.error("empty_cart", "장바구니가 비어있어요. 상품을 담아주세요.")

        # 사용자 정보
        try:
            user = User.objects.get(id=self.user_id)
        except User.DoesNotExist:
            return ResponseBuilder.error("user_not_found", "사용자 정보를 찾을 수 없어요.")

        # 총 가격 계산
        total_price = sum(
            item.selected_product.product.selling_price * item.quantity
            for item in cart_items
        )

        # 주문 생성
        with transaction.atomic():
            order = Order.objects.create(
                user=user,
                total_price=total_price,
                delivery_address=user.address or '배송지를 입력해주세요'
            )

            for item in cart_items:
                OrderItem.objects.create(
                    order=order,
                    selected_product=item.selected_product,
                    purchased_quantity=item.quantity,
                    price_at_order=item.selected_product.product.selling_price,
                    order_status='PENDING'
                )

            # 장바구니 비우기
            CartItem.objects.filter(
                user_id=self.user_id,
                is_deleted=False
            ).update(is_deleted=True)

        return ResponseBuilder.order_created(order.id, total_price, len(cart_items))

    def order_status(self, message: str) -> Dict[str, Any]:
        """주문 상태 조회"""
        from orders.models import Order, OrderItem

        # 주문 ID 파싱
        order_id = self._parse_order_id(message)

        if order_id:
            # 특정 주문 조회
            try:
                order = Order.objects.get(id=order_id, user_id=self.user_id)
                items = list(OrderItem.objects.filter(order=order).select_related(
                    'selected_product__product'
                ))
            except Order.DoesNotExist:
                return ResponseBuilder.error(
                    "order_not_found",
                    "주문을 찾을 수 없어요."
                )

            items_text = "\n".join([
                f"- {item.selected_product.product.product_name}: {item.order_status}"
                for item in items
            ])

            return {
                "text": f"주문 #{order.id} 상태:\n\n{items_text}\n\n"
                        f"총 금액: ₩{order.total_price:,}",
                "type": "order_detail",
                "data": {
                    "order_id": order.id,
                    "total_price": order.total_price,
                    "items": [
                        {
                            "product_name": item.selected_product.product.product_name,
                            "status": item.order_status
                        }
                        for item in items
                    ]
                },
                "suggestions": []
            }

        # 최근 주문 목록
        orders = list(Order.objects.filter(
            user_id=self.user_id,
            is_deleted=False
        ).order_by('-created_at')[:5])

        if not orders:
            return {
                "text": "주문 내역이 없어요.",
                "type": "no_orders",
                "data": {},
                "suggestions": [
                    {"label": "상품 검색", "action": "search"}
                ]
            }

        orders_text = "\n".join([
            f"#{order.id} - ₩{order.total_price:,} ({order.created_at.strftime('%Y-%m-%d')})"
            for order in orders
        ])

        return {
            "text": f"최근 주문 내역:\n\n{orders_text}",
            "type": "order_list",
            "data": {
                "orders": [
                    {
                        "order_id": order.id,
                        "total_price": order.total_price,
                        "created_at": order.created_at.isoformat()
                    }
                    for order in orders
                ]
            },
            "suggestions": []
        }

    def cancel_order(self, message: str) -> Dict[str, Any]:
        """주문 취소"""
        from orders.models import Order, OrderItem

        order_id = self._parse_order_id(message)
        if not order_id:
            return ResponseBuilder.error(
                "no_order_id",
                "취소할 주문 번호를 알려주세요."
            )

        try:
            order = Order.objects.get(id=order_id, user_id=self.user_id)
        except Order.DoesNotExist:
            return ResponseBuilder.error(
                "order_not_found",
                "주문을 찾을 수 없어요."
            )

        # 취소 가능 여부 확인
        items = OrderItem.objects.filter(order=order)
        cancellable_statuses = ['PENDING', 'PAID', 'PREPARING']

        non_cancellable = items.exclude(order_status__in=cancellable_statuses)
        if non_cancellable.exists():
            return ResponseBuilder.error(
                "cannot_cancel",
                "이미 배송 중이거나 완료된 상품이 있어 취소할 수 없어요."
            )

        # 취소 처리
        items.update(order_status='CANCELLED')

        return {
            "text": f"주문 #{order.id}이 취소되었어요.",
            "type": "order_cancelled",
            "data": {"order_id": order.id},
            "suggestions": [
                {"label": "주문 내역", "action": "order_status"}
            ]
        }

    # ============ Helper Methods ============

    def _complete_add_to_cart(
        self,
        selected: Dict[str, Any],
        product_id: int,
        size: str,
        message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """장바구니 추가 완료 (사이즈 선택 후)"""
        from orders.models import CartItem
        from analyses.models import SelectedProduct
        from products.models import SizeCode

        # 수량 파싱 및 검증
        quantity = self._parse_quantity(message)
        if not quantity:
            quantity = 1
        quantity = max(1, min(99, quantity))

        # SizeCode 조회
        size_code = SizeCode.objects.filter(
            product_id=product_id,
            size_value=size,
            is_deleted=False
        ).first()

        # 사이즈 검증: 해당 상품에 존재하는 사이즈인지 확인
        if not size_code:
            # 해당 상품의 가용 사이즈 조회
            available_sizes = list(SizeCode.objects.filter(
                product_id=product_id,
                is_deleted=False
            ).values_list('size_value', flat=True))

            if available_sizes:
                # 사이즈 선택 다시 요청
                context['pending_action'] = {
                    'type': 'select_size_for_cart',
                    'product': selected,
                    'local_product_id': product_id,
                    'available_sizes': available_sizes
                }
                return ResponseBuilder.invalid_size(size, available_sizes)
            else:
                # 사이즈 정보가 없으면 FREE로 처리
                size = 'FREE'
                size_code = None

        # SelectedProduct 생성/조회
        selected_product, _ = SelectedProduct.objects.get_or_create(
            product_id=product_id,
            size_code=size_code,
            defaults={'selected_product_inventory': 0}
        )

        # CartItem 생성/업데이트
        cart_item, created = CartItem.objects.get_or_create(
            user_id=self.user_id,
            selected_product=selected_product,
            is_deleted=False,
            defaults={'quantity': quantity}
        )
        if not created:
            cart_item.quantity += quantity
            cart_item.save()

        # 컨텍스트 업데이트
        context['selected_product'] = selected
        context['selected_size'] = size
        # pending_action 클리어 확인
        context.pop('pending_action', None)

        return ResponseBuilder.cart_added(selected, size, cart_item.quantity)

    def _parse_size(self, message: str) -> Optional[str]:
        """메시지에서 사이즈 추출"""
        # 한글 바로 뒤에 오는 숫자/문자도 매칭되도록 word boundary 대신 lookahead/lookbehind 사용
        size_patterns = [
            r'(?<![A-Za-z])(XS|S|M|L|XL|XXL|XXXL|FREE)(?![A-Za-z])',
            r'(\d{2,3})(?:\s*사이즈|\s*$|[^0-9])',  # 95, 100 등 + 사이즈 or 끝 or 비숫자
            r'(\d+)인치',
        ]

        for pattern in size_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1).upper()

        return None

    def _parse_quantity(self, message: str) -> Optional[int]:
        """메시지에서 수량 추출"""
        patterns = [
            r'(\d+)\s*개',
            r'(\d+)\s*벌',
            r'(\d+)개로',
        ]

        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return int(match.group(1))

        return None

    def _parse_body_info(self, message: str) -> tuple:
        """메시지에서 신체 정보 추출"""
        height = None
        weight = None

        height_match = re.search(r'(\d{2,3})\s*(cm|센치|센티)?', message)
        if height_match:
            h = int(height_match.group(1))
            if 140 <= h <= 220:
                height = h

        weight_match = re.search(r'(\d{2,3})\s*(kg|킬로)?', message)
        if weight_match:
            w = int(weight_match.group(1))
            if 30 <= w <= 150:
                weight = w

        return height, weight

    def _parse_order_id(self, message: str) -> Optional[int]:
        """메시지에서 주문 ID 추출"""
        match = re.search(r'#?(\d+)', message)
        if match:
            return int(match.group(1))
        return None

    def _calculate_size(self, height: int, weight: int, category: str) -> str:
        """신체 정보로 사이즈 계산 (간단한 로직)"""
        bmi = weight / ((height / 100) ** 2)

        if category in ['top', 'outer']:
            if height < 165 and bmi < 22:
                return 'S'
            elif height < 175 and bmi < 25:
                return 'M'
            elif height < 180 and bmi < 27:
                return 'L'
            else:
                return 'XL'
        else:  # bottom
            if bmi < 20:
                return 'S'
            elif bmi < 24:
                return 'M'
            elif bmi < 27:
                return 'L'
            else:
                return 'XL'
