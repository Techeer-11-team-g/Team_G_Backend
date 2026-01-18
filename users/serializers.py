"""
users/serializers.py - 사용자 관련 Serializers

이 모듈은 사용자 인증 및 프로필 관리에 필요한 Serializer들을 정의합니다.

주요 기능:
    - 회원가입 요청/응답 처리
    - 온보딩 정보 업데이트
    - 프로필 조회/수정

Serializers:
    - UserRegisterSerializer: 회원가입 요청
    - UserRegisterResponseSerializer: 회원가입 응답
    - UserOnboardingSerializer: 온보딩 정보 업데이트
    - UserProfileSerializer: 프로필 조회/수정
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


# =============================================================================
# Mixins
# =============================================================================

class UserFieldsMixin:
    """
    사용자 필드 공통 매핑 Mixin
    
    프론트엔드 API 스펙에 맞춰 필드명을 매핑합니다.
    - id -> user_id
    - username -> user_name
    - email -> user_email
    """
    user_id = serializers.IntegerField(source='id', read_only=True)
    user_name = serializers.CharField(source='username', read_only=True)
    user_email = serializers.EmailField(source='email', read_only=True)


# =============================================================================
# 회원가입 Serializers
# =============================================================================

class UserRegisterSerializer(serializers.ModelSerializer):
    """
    회원가입 요청 Serializer
    
    Endpoint: POST /api/v1/auth/register
    
    Request:
        - username (str): 사용자 아이디
        - email (str): 이메일 주소
        - password (str): 비밀번호 (Django 기본 검증 적용)
        - password_confirm (str): 비밀번호 확인
    
    Validation:
        - password와 password_confirm 일치 여부 확인
        - Django 기본 비밀번호 정책 적용 (validate_password)
    """
    password = serializers.CharField(
        write_only=True, 
        required=True, 
        validators=[validate_password]
    )
    password_confirm = serializers.CharField(
        write_only=True, 
        required=True
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm']

    def validate(self, attrs):
        """비밀번호 일치 여부를 검증합니다."""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password_confirm": "비밀번호가 일치하지 않습니다."
            })
        return attrs

    def create(self, validated_data):
        """사용자를 생성합니다."""
        validated_data.pop('password_confirm')
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        return user


class UserRegisterResponseSerializer(serializers.Serializer):
    """
    회원가입 응답 Serializer
    
    API 문서화 및 타입 안전성을 위한 응답 스키마 정의입니다.
    
    Response:
        - user: 생성된 사용자 정보 (user_id, username, email)
        - tokens: JWT 토큰 (refresh, access)
    """
    
    class UserInfoSerializer(serializers.Serializer):
        """사용자 기본 정보"""
        user_id = serializers.IntegerField()
        username = serializers.CharField()
        email = serializers.EmailField()
    
    class TokensSerializer(serializers.Serializer):
        """JWT 토큰 정보"""
        refresh = serializers.CharField()
        access = serializers.CharField()
    
    user = UserInfoSerializer()
    tokens = TokensSerializer()


# =============================================================================
# 온보딩/프로필 Serializers
# =============================================================================

class UserOnboardingSerializer(UserFieldsMixin, serializers.ModelSerializer):
    """
    온보딩 정보 업데이트 Serializer
    
    Endpoint: PATCH /api/v1/users/onboarding
    
    신규 가입 후 필수 정보를 등록하는 온보딩 단계에서 사용됩니다.
    
    Request:
        - user_email (str): 이메일 (수정 가능)
        - address (str): 배송 주소
        - payment (str): 결제 수단
        - phone_number (str): 전화번호
    
    Response:
        - 위 필드 + user_id, user_name, updated_at
    """
    user_email = serializers.EmailField(source='email', required=True)
    user_id = serializers.IntegerField(source='id', read_only=True)
    user_name = serializers.CharField(source='username', read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = User
        fields = [
            'user_email', 'address', 'phone_number', 
            'payment', 'user_id', 'user_name', 'updated_at'
        ]


class UserProfileSerializer(UserFieldsMixin, serializers.ModelSerializer):
    """
    사용자 프로필 조회/수정 Serializer
    
    Endpoints:
        - GET /api/v1/users/profile: 프로필 조회
        - PATCH /api/v1/users/profile: 프로필 수정
    
    Response:
        - user_id (int): 사용자 ID
        - user_name (str): 사용자 아이디
        - user_email (str): 이메일
        - phone_number (str): 전화번호
        - address (str): 배송 주소
        - birth_date (datetime): 생년월일
        - user_image_url (str): 프로필 이미지 URL
        - payment (str): 결제 수단
        - created_at (datetime): 가입 일시
        - updated_at (datetime): 수정 일시
    """
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
