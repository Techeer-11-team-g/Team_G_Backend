from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class UserOnboardingSerializer(serializers.ModelSerializer):
   
    user_email = serializers.EmailField(source='email', required=True)

    class Meta:
        model = User
        fields = ['user_email', 'address', 'phone_number', 'payment']

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