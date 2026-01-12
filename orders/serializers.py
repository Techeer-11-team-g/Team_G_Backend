from rest_framework import serializers
from django.db import transaction
from .models import Order, OrderItem, CartItem

class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'total_price', 'delivery_address', 'created_at']
        read_only_fields = ['id', 'total_price', 'delivery_address', 'created_at']
    
    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Rename 'id' to 'order_id' as per requirement(아이디를 오더 아이디로 변경)
        ret['order_id'] = ret.pop('id')
        return ret 


class OrderCreateSerializer(serializers.ModelSerializer):
    cart_item_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        allow_empty=False
    )
    user_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = Order
        fields = ['cart_item_ids', 'user_id', 'id', 'total_price', 'delivery_address', 'created_at']
        read_only_fields = ['id', 'total_price', 'delivery_address', 'created_at']

    def validate_cart_item_ids(self, value):
        user = self.context['request'].user
        cart_items = CartItem.objects.filter(id__in=value, user=user, is_deleted=False)
        
        if len(cart_items) != len(value):
            raise serializers.ValidationError("유효하지 않은 장바구니 항목이 포함되어 있습니다.")
        
        if not cart_items.exists():
            raise serializers.ValidationError("장바구니 항목을 찾을 수 없습니다.")
            
        return value

    def validate_user_id(self, value):
        user = self.context['request'].user
        if value != user.id:
            raise serializers.ValidationError("잘못된 사용자 ID입니다.")
        return value

    def create(self, validated_data):
        cart_item_ids = validated_data.pop('cart_item_ids')
        user_id = validated_data.pop('user_id') # validated but not used for creation as we use request.user 
        
        user = self.context['request'].user
        
        # 주소가 없는 경우 예외 처리 또는 기본값 설정 (User 모델에 주소가 있다고 가정)
        # User model structure assumes address field based on previous context, using safe access
        delivery_address = getattr(user, 'address', "배송지 정보 없음")
        if not delivery_address:
             delivery_address = "배송지 정보 없음"

        with transaction.atomic():
            cart_items = CartItem.objects.filter(id__in=cart_item_ids, user=user, is_deleted=False)
            
            # 총 주문 금액 계산
            total_price = 0
            for item in cart_items:
                # SelectedProduct -> Product -> selling_price
                price = item.selected_product.product.selling_price
                total_price += price * item.quantity

            # 주문 생성
            order = Order.objects.create(
                user=user,
                total_price=total_price,
                delivery_address=delivery_address, 
            ) 

            # 주문 항목 생성
            order_items = []
            for item in cart_items:
                order_items.append(OrderItem(
                    order=order,
                    product_item=item.selected_product,
                    purchased_quantity=item.quantity,
                    price_at_order=item.selected_product.product.selling_price,
                    order_status=Order.OrderStatus.PAID 
                )) 
            OrderItem.objects.bulk_create(order_items)

            # 장바구니 항목 삭제 (Soft Delete)
            cart_items.update(is_deleted=True)

        return order
    
    def to_representation(self, instance):
        # reuse OrderSerializer's representation for consistency
        return OrderSerializer(instance).data