from rest_framework import serializers
from .models import UploadedImage, ImageAnalysis, DetectedObject, ObjectProductMapping
from products.models import Product


class UploadedImageCreateSerializer(serializers.ModelSerializer):
    """
    이미지 업로드 요청을 처리하는 Serializer
    클라이언트가 POST /api/v1/uploaded-images 요청 시 사용
    """
    # 전송된 파일을 받기 위한 필드 (응답에는 포함되지 않도록 write_only=True 설정)
    file = serializers.ImageField(write_only=True)

    class Meta:
        model = UploadedImage
        fields = ['file']

    def validate_file(self, value):
        """
        업로드된 이미지 파일에 대한 유효성 검사
        """
        # 파일 크기 제한: 10MB
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('파일 크기는 10MB 이하여야 합니다.')

        # 허용된 파일 형식 검사
        allowed_types = ['image/jpeg', 'image/png', 'image/webp']
        if value.content_type not in allowed_types:
            raise serializers.ValidationError('JPG, PNG, WEBP 파일만 업로드 가능합니다.')

        return value

    def create(self, validated_data):
        """
        업로드된 이미지의 메타데이터를 DB에 저장
        """
        file = validated_data['file']
        request = self.context.get('request')

        # 요청한 사용자가 인증되어 있으면 사용자 정보 연결
        user = None
        if request and request.user.is_authenticated:
            user = request.user

        # UploadedImage 객체 생성 및 저장
        uploaded_image = UploadedImage.objects.create(
            user=user,
            uploaded_image_url=file,  # 이미지 필드에 파일 객체 할당 (S3 등에 자동 업로드됨)
        )
        return uploaded_image


class UploadedImageResponseSerializer(serializers.ModelSerializer):
    """
    이미지 업로드 후 성공 응답을 반환하는 Serializer
    """
    # DB의 id 필드를 응답 시 uploaded_image_id로 이름 변경
    uploaded_image_id = serializers.IntegerField(source='id')
    
    # 모델 필드 대신 별도의 로직으로 URL을 가져오기 위한 필드
    uploaded_image_url = serializers.SerializerMethodField()
    
    # 생성일자를 특정 ISO 포맷으로 고정
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%SZ')

    class Meta:
        model = UploadedImage
        fields = ['uploaded_image_id', 'uploaded_image_url', 'created_at']

    def get_uploaded_image_url(self, obj):
        """
        이미지 파일의 절대 경로(URL)를 반환
        """
        if obj.uploaded_image_url:
            return obj.uploaded_image_url.url
        return ''


class UploadedImageListSerializer(serializers.ModelSerializer):
    """
    업로드된 이미지 목록을 조회할 때 사용하는 Serializer
    (현재 구조는 ResponseSerializer와 동일함)
    """
    uploaded_image_id = serializers.IntegerField(source='id')
    uploaded_image_url = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%SZ')

    class Meta:
        model = UploadedImage
        fields = ['uploaded_image_id', 'uploaded_image_url', 'created_at']

    def get_uploaded_image_url(self, obj):
        """
        이미지 파일의 절대 경로(URL)를 반환
        """
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


# =============================================================================
# 이미지 분석 결과 조회용 Serializers
# GET /api/v1/analyses/{analysis_id}
# =============================================================================

class ProductSerializer(serializers.ModelSerializer):
    """
    상품 정보 Serializer
    분석 결과에서 매칭된 상품 정보를 표시
    """
    image_url = serializers.CharField(source='product_image_url')

    class Meta:
        model = Product
        fields = ['id', 'brand_name', 'product_name', 'selling_price', 'image_url', 'product_url']


class MatchSerializer(serializers.ModelSerializer):
    """
    검출 객체-상품 매핑 Serializer
    OpenSearch k-NN 검색으로 찾은 유사 상품 정보
    """
    product_id = serializers.IntegerField(source='product.id')
    product = ProductSerializer()

    class Meta:
        model = ObjectProductMapping
        fields = ['product_id', 'product']


class DetectedObjectResultSerializer(serializers.ModelSerializer):
    """
    검출된 객체 결과 Serializer
    bbox, 카테고리, 매칭된 상품 정보 포함
    """
    detected_object_id = serializers.IntegerField(source='id')
    category_name = serializers.CharField(source='object_category')
    confidence_score = serializers.SerializerMethodField()
    bbox = serializers.SerializerMethodField()
    match = serializers.SerializerMethodField()

    class Meta:
        model = DetectedObject
        fields = ['detected_object_id', 'category_name','confidence_score', 'bbox', 'match']

    def get_confidence_score(self, obj):  
        mapping = obj.product_mappings.filter(is_deleted=False).order_by('-confidence_score').first()
        if mapping:
            return round(mapping.confidence_score, 4)
        return 0.0

    def get_bbox(self, obj):
        """Bounding box 좌표 반환"""
        return {
            'x1': round(obj.bbox_x1, 2),
            'x2': round(obj.bbox_x2, 2),
            'y1': round(obj.bbox_y1, 2),
            'y2': round(obj.bbox_y2, 2),
        }

    def get_match(self, obj):
        """가장 높은 신뢰도의 매칭 상품 반환"""
        mapping = obj.product_mappings.filter(is_deleted=False).order_by('-confidence_score').first()
        if mapping:
            return MatchSerializer(mapping).data
        return None


class UploadedImageInfoSerializer(serializers.ModelSerializer):
    """
    업로드된 이미지 정보 (결과 조회용)
    """
    url = serializers.SerializerMethodField()

    class Meta:
        model = UploadedImage
        fields = ['id', 'url']

    def get_url(self, obj):
        if obj.uploaded_image_url:
            return obj.uploaded_image_url.url
        return ''


class ImageAnalysisResultSerializer(serializers.ModelSerializer):
    """
    이미지 분석 결과 조회 응답용 Serializer
    GET /api/v1/analyses/{analysis_id}
    분석 완료 후 검출된 객체들과 매칭된 상품 정보를 반환
    """
    analysis_id = serializers.IntegerField(source='id')
    uploaded_image = UploadedImageInfoSerializer()
    status = serializers.CharField(source='image_analysis_status')
    items = serializers.SerializerMethodField()

    class Meta:
        model = ImageAnalysis
        fields = ['analysis_id', 'uploaded_image', 'status', 'items']

    def get_items(self, obj):
        """분석된 이미지의 검출된 객체 목록 반환"""
        detected_objects = obj.uploaded_image.detected_objects.filter(is_deleted=False)
        return DetectedObjectResultSerializer(detected_objects, many=True).data


# =============================================================================
# API 6: 자연어 기반 결과 수정
# PATCH /api/v1/analyses
# =============================================================================

class AnalysisRefineRequestSerializer(serializers.Serializer):
    """
    자연어 기반 결과 수정 요청 Serializer
    PATCH /api/v1/analyses
    """
    analysis_id = serializers.IntegerField()
    query = serializers.CharField(help_text='자연어 검색 쿼리 (예: "상의만 다시 검색해줘")')
    detected_object_id = serializers.IntegerField(required=False, help_text='특정 객체만 재검색할 경우')

    def validate_analysis_id(self, value):
        try:
            ImageAnalysis.objects.get(id=value, is_deleted=False)
        except ImageAnalysis.DoesNotExist:
            raise serializers.ValidationError('존재하지 않는 분석입니다.')
        return value

    def validate_detected_object_id(self, value):
        if value:
            try:
                DetectedObject.objects.get(id=value, is_deleted=False)
            except DetectedObject.DoesNotExist:
                raise serializers.ValidationError('존재하지 않는 객체입니다.')
        return value


class AnalysisRefineImageSerializer(serializers.ModelSerializer):
    """API 6 응답용 이미지 정보"""
    uploaded_image_id = serializers.IntegerField(source='id')
    uploaded_image_url = serializers.SerializerMethodField()

    class Meta:
        model = UploadedImage
        fields = ['uploaded_image_id', 'uploaded_image_url']

    def get_uploaded_image_url(self, obj):
        if obj.uploaded_image_url:
            return obj.uploaded_image_url.url
        return ''


class AnalysisRefineItemSerializer(serializers.ModelSerializer):
    """API 6 응답용 검출 객체 Serializer"""
    detected_object_id = serializers.IntegerField(source='id')
    category_name = serializers.CharField(source='object_category')
    confidence_score = serializers.SerializerMethodField()
    bbox = serializers.SerializerMethodField()
    match = serializers.SerializerMethodField()

    class Meta:
        model = DetectedObject
        fields = ['detected_object_id', 'category_name', 'confidence_score', 'bbox', 'match']

    def get_confidence_score(self, obj):
        mapping = obj.product_mappings.filter(is_deleted=False).order_by('-confidence_score').first()
        if mapping:
            return round(mapping.confidence_score, 4)
        return 0.0

    def get_bbox(self, obj):
        return {
            'x1': round(obj.bbox_x1, 2),
            'x2': round(obj.bbox_x2, 2),
            'y1': round(obj.bbox_y1, 2),
            'y2': round(obj.bbox_y2, 2),
        }

    def get_match(self, obj):
        mapping = obj.product_mappings.filter(is_deleted=False).order_by('-confidence_score').first()
        if mapping:
            product = mapping.product
            return {
                'product_id': product.id,
                'product': {
                    'id': product.id,
                    'brand_name': product.brand_name,
                    'product_name': product.product_name,
                    'selling_price': product.selling_price,
                    'image_url': product.product_image_url,
                    'product_url': product.product_url,
                }
            }
        return None


class AnalysisRefineResponseSerializer(serializers.ModelSerializer):
    """
    자연어 기반 결과 수정 응답 Serializer
    PATCH /api/v1/analyses Response
    """
    analysis_id = serializers.IntegerField(source='id')
    status = serializers.CharField(source='image_analysis_status')
    image = AnalysisRefineImageSerializer(source='uploaded_image')
    items = serializers.SerializerMethodField()

    class Meta:
        model = ImageAnalysis
        fields = ['analysis_id', 'status', 'image', 'items']

    def get_items(self, obj):
        detected_objects = obj.uploaded_image.detected_objects.filter(is_deleted=False)
        return AnalysisRefineItemSerializer(detected_objects, many=True).data


# =============================================================================
# API 10: 통합 히스토리 조회
# GET /api/v1/uploaded-images/{uploaded_image_id}
# =============================================================================

class FittingInfoSerializer(serializers.Serializer):
    """피팅 이미지 정보 Serializer"""
    fitting_image_id = serializers.IntegerField()
    fitting_image_url = serializers.CharField()


class HistoryMatchSerializer(serializers.Serializer):
    """
    통합 히스토리 조회용 매칭 정보 Serializer
    product + fitting 정보 포함
    """
    product_id = serializers.IntegerField()
    product = serializers.SerializerMethodField()
    fitting = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.mapping = kwargs.pop('mapping', None)
        super().__init__(*args, **kwargs)

    def get_product(self, obj):
        product = obj
        return {
            'id': product.id,
            'brand_name': product.brand_name,
            'product_name': product.product_name,
            'selling_price': product.selling_price,
            'image_url': product.product_image_url,
            'product_url': product.product_url,
        }

    def get_fitting(self, obj):
        """해당 상품에 대한 피팅 이미지 조회"""
        from fittings.models import FittingImage

        # 완료된 피팅 이미지 중 가장 최신 것 반환
        fitting = FittingImage.objects.filter(
            product=obj,
            fitting_image_status='DONE',
            is_deleted=False
        ).order_by('-created_at').first()

        if fitting and fitting.fitting_image_url:
            return {
                'fitting_image_id': fitting.id,
                'fitting_image_url': fitting.fitting_image_url,
            }
        return None


class HistoryItemSerializer(serializers.ModelSerializer):
    """
    통합 히스토리 조회용 검출 객체 Serializer
    피팅 정보 포함
    """
    detected_object_id = serializers.IntegerField(source='id')
    category_name = serializers.CharField(source='object_category')
    confidence_score = serializers.SerializerMethodField()
    bbox = serializers.SerializerMethodField()
    match = serializers.SerializerMethodField()

    class Meta:
        model = DetectedObject
        fields = ['detected_object_id', 'category_name', 'confidence_score', 'bbox', 'match']

    def get_confidence_score(self, obj):
        mapping = obj.product_mappings.filter(is_deleted=False).order_by('-confidence_score').first()
        if mapping:
            return round(mapping.confidence_score, 4)
        return 0.0

    def get_bbox(self, obj):
        return {
            'x1': round(obj.bbox_x1, 2),
            'x2': round(obj.bbox_x2, 2),
            'y1': round(obj.bbox_y1, 2),
            'y2': round(obj.bbox_y2, 2),
        }

    def get_match(self, obj):
        """매칭된 상품 + 피팅 정보 반환"""
        from fittings.models import FittingImage

        mapping = obj.product_mappings.filter(is_deleted=False).order_by('-confidence_score').first()
        if not mapping:
            return None

        product = mapping.product

        # 피팅 이미지 조회
        fitting_data = None
        fitting = FittingImage.objects.filter(
            product=product,
            fitting_image_status='DONE',
            is_deleted=False
        ).order_by('-created_at').first()

        if fitting and fitting.fitting_image_url:
            fitting_data = {
                'fitting_image_id': fitting.id,
                'fitting_image_url': fitting.fitting_image_url,
            }

        return {
            'product_id': product.id,
            'product': {
                'id': product.id,
                'brand_name': product.brand_name,
                'product_name': product.product_name,
                'selling_price': product.selling_price,
                'image_url': product.product_image_url,
                'product_url': product.product_url,
            },
            'fitting': fitting_data,
        }


class UploadedImageHistoryResponseSerializer(serializers.Serializer):
    """
    통합 히스토리 조회 응답 Serializer
    GET /api/v1/uploaded-images/{uploaded_image_id}
    """
    items = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.detected_objects = kwargs.pop('detected_objects', [])
        super().__init__(*args, **kwargs)

    def get_items(self, obj):
        return HistoryItemSerializer(self.detected_objects, many=True).data
