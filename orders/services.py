import logging
from django.db import transaction
from .models import Order, OrderItem, CartItem
from analyses.models import SelectedProduct
from analyses.utils import create_span

logger = logging.getLogger(__name__)

TRACER_NAME = "orders.services"


def add_to_cart(user, selected_product_id, quantity):
    """장바구니 항목 추가 또는 수량 업데이트"""
    with create_span(TRACER_NAME, "add_to_cart") as ctx:
        ctx.set("user.id", user.id)
        ctx.set("selected_product_id", selected_product_id)

        selected_product = SelectedProduct.objects.get(id=selected_product_id)

        cart_item, created = CartItem.objects.get_or_create(
            user=user,
            selected_product=selected_product,
            defaults={'quantity': quantity}
        )

        if not created:
            cart_item.quantity += quantity
            cart_item.save(update_fields=['quantity', 'updated_at'])

        ctx.set("cart_item.id", cart_item.id)
        ctx.set("created", created)

        return cart_item


def create_order(user, cart_item_ids, payment_method):
    """장바구니 항목을 바탕으로 주문 생성"""
    with create_span(TRACER_NAME, "create_order") as ctx:
        ctx.set("user.id", user.id)
        ctx.set("cart_item_count", len(cart_item_ids))

        delivery_address = getattr(user, 'address', "배송지 정보 없음") or "배송지 정보 없음"

        with transaction.atomic():
            cart_items = CartItem.objects.filter(id__in=cart_item_ids, user=user)

            if not cart_items.exists():
                raise ValueError("유효한 장바구니 항목이 없습니다.")

            total_price = sum(
                item.selected_product.product.selling_price * item.quantity
                for item in cart_items
            )

            order = Order.objects.create(
                user=user,
                total_price=total_price,
                delivery_address=delivery_address,
            )

            order_items = [
                OrderItem(
                    order=order,
                    selected_product=item.selected_product,
                    purchased_quantity=item.quantity,
                    price_at_order=item.selected_product.product.selling_price,
                    order_status=OrderItem.OrderStatus.PAID
                ) for item in cart_items
            ]
            OrderItem.objects.bulk_create(order_items)

            cart_items.delete()

            ctx.set("order.id", order.id)
            ctx.set("total_price", total_price)

            return order


def cancel_order(order, user):
    """주문 취소 logic"""
    with create_span(TRACER_NAME, "cancel_order") as ctx:
        ctx.set("order.id", order.id)

        cancellable_statuses = [
            OrderItem.OrderStatus.PENDING,
            OrderItem.OrderStatus.PAID,
            OrderItem.OrderStatus.PREPARING
        ]

        if order.order_items.exclude(order_status__in=cancellable_statuses).exists():
            raise ValueError("이미 배송 중이거나 취소 불가능한 상태입니다.")

        with transaction.atomic():
            order.order_items.all().update(order_status=OrderItem.OrderStatus.CANCELLED)
            order.save()

            return order
