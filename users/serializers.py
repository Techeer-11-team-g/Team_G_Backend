from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class UserRegisterSerializer(serializers.ModelSerializer):
    """회원가입 Serializer"""
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm']

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "비밀번호가 일치하지 않습니다."})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        return user


class UserOnboardingSerializer(serializers.ModelSerializer):
    # 프론트에서 user_email로 보낸다니 source를 이용해 매핑 가능
    user_email = serializers.EmailField(source='email', required=True) 
    user_id = serializers.IntegerField(source='id', read_only=True)
    user_name = serializers.CharField(source='username', read_only=True)
    updated_at = serializers.DateTimeField(read_only=True) 

    class Meta:
        model = User
        fields = [
            'user_email', 'address', 'phone_number', 
            'payment', "user_id", "user_name", "updated_at"
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
