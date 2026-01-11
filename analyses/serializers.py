from rest_framework import serializers
from .models import UploadedImage


class UploadedImageCreateSerializer(serializers.ModelSerializer):
    """
    이미지 업로드 요청용
    POST /api/v1/uploaded-images
    """
    file = serializers.ImageField(write_only=True)

    class Meta:
        model = UploadedImage
        fields = ['file']

    def validate_file(self, value):
        """파일 검증"""
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('파일 크기는 10MB 이하여야 합니다.')

        allowed_types = ['image/jpeg', 'image/png', 'image/webp']
        if value.content_type not in allowed_types:
            raise serializers.ValidationError('JPG, PNG, WEBP 파일만 업로드 가능합니다.')

        return value

    def create(self, validated_data):
        """이미지 저장"""
        file = validated_data['file']
        request = self.context.get('request')

        user = None
        if request and request.user.is_authenticated:
            user = request.user

        uploaded_image = UploadedImage.objects.create(
            user=user,
            uploaded_image_url=file,  # 필드명 변경됨
        )
        return uploaded_image


class UploadedImageResponseSerializer(serializers.ModelSerializer):
    """
    이미지 업로드 응답용
    Response: { uploaded_image_id, uploaded_image_url, created_at }
    """
    uploaded_image_id = serializers.IntegerField(source='id')
    uploaded_image_url = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%SZ')

    class Meta:
        model = UploadedImage
        fields = ['uploaded_image_id', 'uploaded_image_url', 'created_at']

    def get_uploaded_image_url(self, obj):
        if obj.uploaded_image_url:
            return obj.uploaded_image_url.url
        return ''


class UploadedImageListSerializer(serializers.ModelSerializer):
    """
    이미지 목록 조회용
    GET /api/v1/uploaded-images
    """
    uploaded_image_id = serializers.IntegerField(source='id')
    uploaded_image_url = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%SZ')

    class Meta:
        model = UploadedImage
        fields = ['uploaded_image_id', 'uploaded_image_url', 'created_at']

    def get_uploaded_image_url(self, obj):
        if obj.uploaded_image_url:
            return obj.uploaded_image_url.url
        return ''