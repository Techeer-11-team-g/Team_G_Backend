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


class ImageAnalysisCreateSerializer(serializers.Serializer):
    """
    업로드된 이미지를 기반으로 AI 분석을 요청할 때 사용되는 Serializer
    """
    # 분석할 이미지를 식별하기 위한 ID
    uploaded_image_id = serializers.IntegerField()
    
    # 부가적인 이미지 URL (필요시 사용)
    uploaded_image_url = serializers.CharField(required=False, allow_blank=True)

    def validate_uploaded_image_id(self, value):
        """
        입력된 이미지 ID가 유효한지 검사 (존재 여부 및 삭제 여부 확인)
        """
        try:
            uploaded_image = UploadedImage.objects.get(id=value, is_deleted=False)
        except UploadedImage.DoesNotExist:
            raise serializers.ValidationError('존재하지 않는 이미지입니다.')
        return value

    def create(self, validated_data):
        """
        새로운 이미지 분석(ImageAnalysis) 레코드를 생성하여 분석 대기 상태로 설정
        """
        uploaded_image_id = validated_data['uploaded_image_id']
        uploaded_image = UploadedImage.objects.get(id=uploaded_image_id)

        # 초기 상태를 'PENDING'으로 설정하여 DB에 저장
        analysis = ImageAnalysis.objects.create(
            uploaded_image=uploaded_image,
            image_analysis_status=ImageAnalysis.Status.PENDING,
        )
        return analysis


class ImageAnalysisResponseSerializer(serializers.ModelSerializer):
    """
    이미지 분석 요청 성공 후 반환되는 응답 Serializer
    상태 확인 및 결과 조회를 위한 URL 정보 포함
    """
    analysis_id = serializers.IntegerField(source='id')
    status = serializers.CharField(source='image_analysis_status')
    
    # 진행 상태(Polling)를 확인하기 위한 API 경로 정보 제공
    polling = serializers.SerializerMethodField()

    class Meta:
        model = ImageAnalysis
        fields = ['analysis_id', 'status', 'polling']

    def get_polling(self, obj):
        """
        상태 조회 및 결과 조회를 위한 엔드포인트 생성
        """
        return {
            'status_url': f'/api/v1/analyses/{obj.id}/status', # 실시간 상태 확인용
            'result_url': f'/api/v1/analyses/{obj.id}',        # 분석 완료 후 최종 결과용
        }


class ImageAnalysisStatusSerializer(serializers.ModelSerializer):
    """
    이미지 분석 상태 조회 응답용 Serializer
    GET /api/v1/analyses/{analysis_id}/status
    Redis에서 실시간 진행률을 가져와 함께 반환
    """
    analysis_id = serializers.IntegerField(source='id')
    status = serializers.CharField(source='image_analysis_status')
    progress = serializers.IntegerField(default=0)
    updated_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%SZ')

    class Meta:
        model = ImageAnalysis
        fields = ['analysis_id', 'status', 'progress', 'updated_at']
