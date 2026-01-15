from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class UserOnboardingSerializer(serializers.ModelSerializer):
    # 프론트에서 user_email로 보낸다니 source를 이용해 매핑 가능
    user_email = serializers.EmailField(source='email', required=True)
    
    user_id = serializers.IntegerField(source='id', read_only=True)
    user_name = serializers.CharField(source='username', read_only=True)
    updated_at = serializers.DateTimeField(source='updated_at', read_only=True) 

    class Meta:
        model = User
        fields = [
            'user_email', 
            'address', 
            'phone_number', 
            'payment', 
            "user_id", 
            "user_name", 
            "updated_at"
        ]

class UserProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='id', read_only=True)
    user_name = serializers.CharField(source='username', read_only=True)
    user_email = serializers.EmailField(source='email', read_only=True)

    class Meta:
        model = User
        fields = [
            'user_id', 
            'user_name', 
            'user_email', 
            'phone_number', 
            'address', 
            'birth_date', 
            'user_image_url', 
            'payment', 
            'updated_at',
            'created_at'
        ]
