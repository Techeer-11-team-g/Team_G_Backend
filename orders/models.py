from django.db import models
from django.conf import settings


class CartItem(models.Model):
    """
    장바구니 항목 테이블
    ERD: cart_item
    사용자별 장바구니 정보
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cart_items',
        db_column='user_id',
        verbose_name='사용자',
    )

    selected_product = models.ForeignKey(
        'analyses.SelectedProduct',
        on_delete=models.CASCADE,
        related_name='cart_items',
        db_column='selected_product_id',
        verbose_name='선택된 상품',
    )

    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name='수량',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 일자',
    )

    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    class Meta:
        db_table = 'cart_item'
        verbose_name = '장바구니 항목'
        verbose_name_plural = '장바구니 항목 목록'

    def __str__(self):
        return f"CartItem #{self.pk} - {self.user} / {self.selected_product}"


class Order(models.Model):
    """
    주문 테이블
    ERD: order
    주문 기본 정보
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='orders',
        db_column='user_id',
        verbose_name='사용자',
    )

    total_price = models.PositiveIntegerField(
        default=0,
        verbose_name='총 주문 금액',
    )

    delivery_address = models.TextField(
        verbose_name='배송 주소',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 일자',
    )

    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    class Meta:
        db_table = 'order'
        ordering = ['-created_at']
        verbose_name = '주문'
        verbose_name_plural = '주문 목록'

    def __str__(self):
        return f"Order #{self.pk}"


class OrderItem(models.Model):
    """
    주문 항목 테이블
    ERD: order_item
    주문에 포함된 개별 상품 항목
    """
    class OrderStatus(models.TextChoices):
        PENDING = 'PENDING', '결제 대기'
        PAID = 'PAID', '결제 완료'
        PREPARING = 'PREPARING', '배송 준비 중'
        SHIPPING = 'SHIPPING', '배송 중'
        DELIVERED = 'DELIVERED', '배송 완료'
        CANCELLED = 'CANCELLED', '주문 취소'
        REFUNDED = 'REFUNDED', '환불 완료'

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='order_items',
        db_column='order_id',
        verbose_name='주문',
    )

    product_item = models.ForeignKey(
        'analyses.SelectedProduct',
        on_delete=models.SET_NULL,
        null=True,
        related_name='order_items',
        db_column='product_item_id',
        verbose_name='상품 아이템',
    )

    purchased_quantity = models.PositiveIntegerField(
        default=1,
        verbose_name='구매 수량',
    )

    price_at_order = models.PositiveIntegerField(
        default=0,
        verbose_name='주문 시점 가격',
        help_text='주문 시점의 상품 가격 (가격 변동 대비)',
    )

    order_status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        verbose_name='주문 상태',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 일자',
    )

    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    class Meta:
        db_table = 'order_item'
        verbose_name = '주문 항목'
        verbose_name_plural = '주문 항목 목록'

    def __str__(self):
        return f"OrderItem #{self.pk} - {self.order}"

    @property
    def subtotal(self):
        """해당 주문 항목의 소계"""
        return self.price_at_order * self.purchased_quantity
