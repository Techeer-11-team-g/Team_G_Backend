from rest_framework import serializers
from .models import FittingImage, UserImage
from products.models import Product


class UserImageUploadSerializer(serializers.ModelSerializer):
    """
    사용자 이미지 업로드용 Serializer
    POST /api/v1/user-images - 사용자 전신 이미지 업로드
    """
    # Response 필드
    user_image_id = serializers.IntegerField(source='id', read_only=True)
    user_image_url = serializers.SerializerMethodField(read_only=True)
    created_at = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", read_only=True)

    # Request 필드 (파일 업로드)
    file = serializers.ImageField(write_only=True)

    class Meta:
        model = UserImage
        fields = ['user_image_id', 'user_image_url', 'created_at', 'file']

    def get_user_image_url(self, obj):
        if obj.user_image_url:
            # ImageField인 경우 .url 반환, URLField인 경우 그대로 반환
            if hasattr(obj.user_image_url, 'url'):
                return obj.user_image_url.url
            return str(obj.user_image_url)
        return ''

    def validate_file(self, value):
        """파일 유효성 검사"""
        # 파일 크기 제한: 10MB
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('파일 크기는 10MB 이하여야 합니다.')

        # 허용된 파일 형식 검사
        allowed_types = ['image/jpeg', 'image/png', 'image/webp']
        if value.content_type not in allowed_types:
            raise serializers.ValidationError('JPG, PNG, WEBP 파일만 업로드 가능합니다.')

        return value

    def create(self, validated_data):
        """사용자 이미지 저장"""
        file = validated_data.pop('file')
        request = self.context.get('request')
        user = request.user  # JWT 인증된 유저

        user_image = UserImage.objects.create(
            user=user,
            user_image_url=file  # ImageField에 파일 저장
        )
        return user_image


class FittingImageSerializer(serializers.ModelSerializer):
    """
    가상 피팅 요청용 Serializer
    POST /api/v1/fitting-images - 가상 피팅 요청

    user_image_url: 이미 업로드된 사용자 이미지의 URL을 받아서 처리
    """
    # Response 필드들 (read_only)
    fitting_image_id = serializers.IntegerField(source='id', read_only=True)
    fitting_image_status = serializers.CharField(read_only=True)
    fitting_image_url = serializers.URLField(read_only=True)
    polling = serializers.SerializerMethodField(read_only=True)
    completed_at = serializers.DateTimeField(
        source='updated_at',
        format="%Y-%m-%dT%H:%M:%SZ",
        read_only=True
    )

    # Request 필드들 (write_only)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source='product',
        write_only=True
    )
    user_image_url = serializers.CharField(write_only=True)

    class Meta:
        model = FittingImage
        fields = [
            'fitting_image_id', 'fitting_image_status', 'fitting_image_url',
            'polling', 'completed_at',
            'product_id', 'user_image_url'
        ]

    def get_polling(self, obj):
        return {
            "status_url": f"/api/v1/fitting-images/{obj.id}/status",
            "result_url": f"/api/v1/fitting-images/{obj.id}"
        }

    def validate_user_image_url(self, value):
        """
        user_image_url 검증:
        - 기존에 업로드된 UserImage의 URL을 찾아서 반환
        - DB 레벨에서 필터링하여 성능 최적화
        """
        from django.db.models import Q
        import re

        # URL에서 경로 부분 추출 (전체 URL 또는 상대 경로 모두 지원)
        search_value = value

        # GCS URL 패턴: https://storage.googleapis.com/{bucket}/{path}
        gcs_match = re.match(r'https://storage\.googleapis\.com/[^/]+/(.+)', value)
        if gcs_match:
            search_value = gcs_match.group(1)
        elif '/media/' in value:
            search_value = value.split('/media/')[-1]
        elif value.startswith('/'):
            search_value = value.lstrip('/')

        # DB 레벨에서 LIKE 쿼리로 필터링 (전체 순회 대신)
        user_image = UserImage.objects.filter(
            Q(user_image_url__exact=value) |
            Q(user_image_url__exact=search_value) |
            Q(user_image_url__endswith=search_value),
            is_deleted=False
        ).first()
        
        if user_image:
            return user_image

        raise serializers.ValidationError('존재하지 않는 사용자 이미지 URL입니다. 먼저 /api/v1/user-images 에서 이미지를 업로드하세요.')

    def create(self, validated_data):
        """FittingImage 생성"""
        user_image = validated_data.pop('user_image_url')
        validated_data['user_image'] = user_image
        return super().create(validated_data)


class FittingStatusSerializer(serializers.ModelSerializer):
    """
    가상 피팅 상태 조회용 Serializer
    GET /api/v1/fitting-images/{fitting_image_id}/status
    """
    fitting_image_status = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ")

    class Meta:
        model = FittingImage
        fields = ['fitting_image_status', 'progress', 'updated_at']

    def get_fitting_image_status(self, obj):
        return obj.fitting_image_status.upper()

    def get_progress(self, obj):
        if obj.fitting_image_status == FittingImage.Status.RUNNING:
            return 40
        elif obj.fitting_image_status == FittingImage.Status.DONE:
            return 100
        elif obj.fitting_image_status == FittingImage.Status.FAILED:
            return 0
        return 0


class FittingResultSerializer(serializers.ModelSerializer):
    """
    가상 피팅 결과 조회용 Serializer
    GET /api/v1/fitting-images/{fitting_image_id}
    """
    fitting_image_id = serializers.IntegerField(source='id', read_only=True)
    fitting_image_status = serializers.SerializerMethodField()
    fitting_image_url = serializers.URLField(read_only=True)
    completed_at = serializers.DateTimeField(
        source='updated_at',
        format="%Y-%m-%dT%H:%M:%SZ",
        read_only=True
    )

    class Meta:
        model = FittingImage
        fields = ['fitting_image_id', 'fitting_image_status', 'fitting_image_url', 'completed_at']

    def get_fitting_image_status(self, obj):
        return obj.fitting_image_status.upper()
