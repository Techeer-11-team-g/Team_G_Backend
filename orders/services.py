import logging
from django.db import transaction
from .models import Order, OrderItem, CartItem
from analyses.models import SelectedProduct 
from contextlib import nullcontext

logger = logging.getLogger(__name__)

def _get_tracer():
    """Get tracer lazily to ensure TracerProvider is initialized."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("orders.services")
    except ImportError:
        return None

def _create_span(name: str):
    """Create a span if tracer is available."""
    tracer = _get_tracer()
    if tracer:
        return tracer.start_as_current_span(name)
    return nullcontext()

def add_to_cart(user, selected_product_id, quantity):
    """장바구니 항목 추가 또는 수량 업데이트"""
    with _create_span("service_add_to_cart") as span:
        selected_product = SelectedProduct.objects.get(id=selected_product_id)
        
        cart_item, created = CartItem.objects.get_or_create(
            user=user,
            selected_product=selected_product,
            defaults={'quantity': quantity}
        )

        if not created:
            cart_item.quantity += quantity
            cart_item.save(update_fields=['quantity', 'updated_at'])
        
        if span and hasattr(span, 'set_attribute'):
            span.set_attribute("cart_item.id", cart_item.id)
            span.set_attribute("created", created)
            
        return cart_item

def create_order(user, cart_item_ids, payment_method):
    """장바구니 항목을 바탕으로 주문 생성"""
    with _create_span("service_create_order") as span:
        delivery_address = getattr(user, 'address', "배송지 정보 없음") or "배송지 정보 없음"

        with transaction.atomic():
            cart_items = CartItem.objects.filter(id__in=cart_item_ids, user=user)
            
            # 총 주문 금액 계산
            total_price = sum(
                item.selected_product.product.selling_price * item.quantity 
                for item in cart_items
            )

            # 주문 생성
            order = Order.objects.create(
                user=user,
                total_price=total_price,
                delivery_address=delivery_address, 
            ) 

            # 주문 항목 생성
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

            # 장바구니 항목 삭제 (Soft Delete via manager)
            cart_items.delete()

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("order.id", order.id)
                span.set_attribute("total_price", total_price)

            return order

def cancel_order(order, user):
    """주문 취소 logic"""
    with _create_span("service_cancel_order") as span:
        cancellable_statuses = [
            OrderItem.OrderStatus.PENDING,
            OrderItem.OrderStatus.PAID,
            OrderItem.OrderStatus.PREPARING
        ]
        
        if order.order_items.exclude(order_status__in=cancellable_statuses).exists():
            raise ValueError("이미 배송 중이거나 취소 불가능한 상태입니다.")
        
        with transaction.atomic():
            order.order_items.all().update(order_status=OrderItem.OrderStatus.CANCELLED)
            order.save() # updated_at trigger

            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("order.id", order.id)
                
            return order
