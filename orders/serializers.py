from rest_framework import serializers
from .models import Order, OrderItem, CartItem 
from analyses.models import SelectedProduct
from . import services


class ProductDetailsSerializer(serializers.Serializer):
    """장바구니 상품 상세 정보"""
    product_id = serializers.IntegerField(source='product.id')
    brand_name = serializers.CharField(source='product.brand_name')
    product_name = serializers.CharField(source='product.product_name')
    selling_price = serializers.IntegerField(source='product.selling_price')
    main_image_url = serializers.CharField(source='product.product_image_url')
    product_url = serializers.CharField(source='product.product_url')
    size = serializers.CharField(source='size_code.size_value', allow_null=True)
    inventory = serializers.IntegerField(source='selected_product_inventory')


class CartItemSerializer(serializers.ModelSerializer):
    """장바구니 조회용 Serializer"""
    cart_item_id = serializers.IntegerField(source='id', read_only=True)
    selected_product_id = serializers.IntegerField(source='selected_product.id', read_only=True)
    product_details = ProductDetailsSerializer(source='selected_product', read_only=True)
    created_at = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%S", read_only=True)

    class Meta:
        model = CartItem
        fields = ['cart_item_id', 'selected_product_id', 'quantity', 'product_details', 'created_at']


class CartItemCreateSerializer(serializers.ModelSerializer):
    """장바구니 추가용 Serializer"""
    selected_product_id = serializers.IntegerField(write_only=True)
    quantity = serializers.IntegerField(min_value=1)

    class Meta:
        model = CartItem
        fields = ['selected_product_id', 'quantity']

    def validate_selected_product_id(self, value):
        if not SelectedProduct.objects.filter(id=value).exists():
            raise serializers.ValidationError("해당 상품을 찾을 수 없습니다.")
        return value

    def create(self, validated_data):
        return services.add_to_cart(
            user=self.context['request'].user,
            selected_product_id=validated_data['selected_product_id'],
            quantity=validated_data['quantity']
        )

    def to_representation(self, instance):
        return {
            'cart_id': instance.id,
            'selected_product_id': instance.selected_product.id,
            'quantity': instance.quantity,
            'created_at': instance.created_at.strftime("%Y-%m-%dT%H:%M:%S")
        }


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'total_price', 'delivery_address', 'created_at']
        read_only_fields = ['id', 'total_price', 'delivery_address', 'created_at']
    
    def to_representation(self, instance):
        ret = super().to_representation(instance) 
        ret['order_id'] = ret.pop('id')
        first_item = instance.order_items.first()
        ret['order_status'] = first_item.order_status if first_item else None
        return ret


class OrderItemDetailSerializer(serializers.ModelSerializer):
    order_item_id = serializers.IntegerField(source='id')
    selected_product_id = serializers.IntegerField(source='selected_product.id')
    product_name = serializers.CharField(source='selected_product.product.product_name')

    class Meta:
        model = OrderItem
        fields = ['order_item_id', 'order_status', 'selected_product_id', 'purchased_quantity', 'price_at_order', 'product_name']


class OrderDetailSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source='id')
    order_items = OrderItemDetailSerializer(many=True, read_only=True)
    
    class Meta:
        model = Order
        fields = ['order_id', 'total_price', 'delivery_address', 'order_items', 'created_at', 'updated_at']


class OrderListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'total_price', 'created_at']
        read_only_fields = ['id', 'total_price', 'created_at']

    def to_representation(self, instance):
        ret = super().to_representation(instance) 
        ret['order_id'] = ret.pop('id')
        return ret


class OrderCreateSerializer(serializers.ModelSerializer):
    cart_item_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        allow_empty=False
    )
    user_id = serializers.IntegerField(write_only=True)
    payment_method = serializers.CharField(write_only=True)
     
    class Meta:
        model = Order
        fields = ['cart_item_ids', 'user_id', 'payment_method', 'id', 'total_price', 'delivery_address', 'created_at']
        read_only_fields = ['id', 'total_price', 'delivery_address', 'created_at']

    def validate_cart_item_ids(self, value):
        user = self.context['request'].user
        if CartItem.objects.filter(id__in=value, user=user).count() != len(value):
            raise serializers.ValidationError("유효하지 않은 장바구니 항목이 포함되어 있습니다.") 
        return value

    def validate_user_id(self, value):
        if value != self.context['request'].user.id:
            raise serializers.ValidationError("잘못된 사용자 ID입니다.")
        return value

    def create(self, validated_data):
        return services.create_order(
            user=self.context['request'].user,
            cart_item_ids=validated_data['cart_item_ids'],
            payment_method=validated_data['payment_method']
        )
    
    def to_representation(self, instance):
        # reuse OrderSerializer's representation for consistency
        return OrderSerializer(instance).data 

class OrderCancelSerializer(serializers.ModelSerializer):
    order_status = serializers.CharField(write_only=True)
    class Meta:
        model = Order
        fields = ['order_status']

    def validate_order_status(self, value):
        if value != 'canceled':
            raise serializers.ValidationError("order_status는 'canceled'여야 합니다.")
        return value

    def validate(self, attrs):
        # 취소 가능 상태: 결제 대기(PENDING), 결제 완료(PAID), 배송 준비 중(PREPARING)
        cancellable_statuses = [
            OrderItem.OrderStatus.PENDING,
            OrderItem.OrderStatus.PAID,
            OrderItem.OrderStatus.PREPARING
        ]
        
        # 주문에 포함된 항목 중 하나라도 취소 불가능한 상태(배송 중, 배송 완료, 이미 취소됨 등)가 있으면 에러 발생
        if self.instance.order_items.exclude(order_status__in=cancellable_statuses).exists():
            raise serializers.ValidationError("이미 배송 중이거나 취소 불가능한 상태입니다.") 
    def update(self, instance, validated_data):
        try:
            return services.cancel_order(instance, self.context['request'].user)
        except ValueError as e:
            raise serializers.ValidationError(str(e))

    def to_representation(self, instance):
        return { 
            "order_id": instance.id,
            "order_status": "cancelled",
            "updated_at": instance.updated_at 
        }