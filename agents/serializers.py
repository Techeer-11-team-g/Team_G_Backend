"""
AI 패션 어시스턴트 - 직렬화
채팅 API 요청/응답 직렬화
"""

from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):
    """채팅 요청 직렬화"""
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="사용자 메시지"
    )
    session_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="세션 ID (없으면 새 세션 생성)"
    )
    # 이미지는 MultiPartParser에서 처리

    def validate(self, data):
        """메시지 또는 이미지 중 하나는 필수"""
        # 이미지는 view에서 별도 처리
        return data


class ProductSerializer(serializers.Serializer):
    """상품 직렬화"""
    index = serializers.IntegerField()
    product_id = serializers.IntegerField()
    brand_name = serializers.CharField()
    product_name = serializers.CharField()
    selling_price = serializers.IntegerField()
    image_url = serializers.URLField(allow_blank=True)
    product_url = serializers.URLField(allow_blank=True)
    sizes = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )


class SuggestionSerializer(serializers.Serializer):
    """후속 액션 제안 직렬화"""
    label = serializers.CharField()
    action = serializers.CharField()


class ResponseDataSerializer(serializers.Serializer):
    """응답 데이터 직렬화"""
    products = ProductSerializer(many=True, required=False)
    total_count = serializers.IntegerField(required=False)
    fitting_image_url = serializers.URLField(required=False)
    fitting_id = serializers.IntegerField(required=False)
    status_url = serializers.CharField(required=False)
    analysis_id = serializers.IntegerField(required=False)
    order_id = serializers.IntegerField(required=False)
    error_type = serializers.CharField(required=False)


class ChatResponseContentSerializer(serializers.Serializer):
    """채팅 응답 내용 직렬화"""
    text = serializers.CharField()
    type = serializers.CharField()
    data = ResponseDataSerializer(required=False)
    suggestions = SuggestionSerializer(many=True, required=False)


class ContextSerializer(serializers.Serializer):
    """컨텍스트 정보 직렬화"""
    current_analysis_id = serializers.IntegerField(allow_null=True)
    has_search_results = serializers.BooleanField()
    has_user_image = serializers.BooleanField()
    cart_item_count = serializers.IntegerField(required=False)


class ChatResponseSerializer(serializers.Serializer):
    """채팅 응답 직렬화"""
    session_id = serializers.CharField()
    response = ChatResponseContentSerializer()
    context = ContextSerializer(required=False)


class StatusCheckRequestSerializer(serializers.Serializer):
    """상태 확인 요청 직렬화"""
    type = serializers.ChoiceField(choices=['analysis', 'fitting'])
    id = serializers.IntegerField()
