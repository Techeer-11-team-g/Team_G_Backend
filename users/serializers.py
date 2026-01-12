from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class UserOnboardingSerializer(serializers.ModelSerializer):
    # 프론트에서 user_email로 보낸다니 source를 이용해 매핑 가능
    user_email = serializers.EmailField(source='email', required=True)

    class Meta:
        model = User
        # 모델에 payment 필드가 추가되었으므로 fields에 포함시키면 자동으로 처리됩니다.
        fields = ['user_email', 'address', 'phone_number', 'payment']


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        # 응답으로 내려줄 필드들만 선택합니다.
        fields = [
            'id', 'username', 'email', 'phone_number', 
            'address', 'birth_date', 'user_image_url', 
            'payment', 'created_at'
        ]
        # 조회 전용이므로 읽기 전용 필드로 설정할 수 있습니다.
        read_only_fields = ['id', 'username', 'email', 'created_at']