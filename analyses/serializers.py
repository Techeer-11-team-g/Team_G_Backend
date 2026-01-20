"""
analyses 앱 Serializers.

리팩토링:
- 중복 Serializer 통합 (Base 클래스 활용)
- Mixin으로 공통 메서드 추출
- N+1 쿼리 해결 (prefetch 활용)
"""

from rest_framework import serializers
from .models import UploadedImage, ImageAnalysis, DetectedObject, ObjectProductMapping, SelectedProduct
from .utils import format_bbox_for_api
from products.models import Product, SizeCode


# =============================================================================
# Mixins - 공통 메서드 추출
# =============================================================================

class BboxSerializerMixin:
    """Bbox 관련 공통 메서드를 제공하는 Mixin."""

    def get_bbox(self, obj):
        """DetectedObject의 bbox를 API 응답 형식으로 변환."""
        return format_bbox_for_api(obj)


class ConfidenceScoreMixin:
    """신뢰도 점수 관련 공통 메서드를 제공하는 Mixin."""

    def get_confidence_score(self, obj):
        """가장 높은 신뢰도의 매핑 점수 반환."""
        # prefetch된 product_mappings 사용
        mappings = getattr(obj, '_prefetched_objects_cache', {}).get('product_mappings')
        if mappings is not None:
            valid_mappings = [m for m in mappings if not m.is_deleted]
            if valid_mappings:
                best = max(valid_mappings, key=lambda m: m.confidence_score)
                return round(best.confidence_score, 4)
        else:
            # prefetch 안 된 경우 쿼리 실행
            mapping = obj.product_mappings.filter(is_deleted=False).order_by('-confidence_score').first()
            if mapping:
                return round(mapping.confidence_score, 4)
        return 0.0


# =============================================================================
# 이미지 업로드 Serializers
# =============================================================================

class UploadedImageCreateSerializer(serializers.ModelSerializer):
    """
    이미지 업로드 요청을 처리하는 Serializer.
    POST /api/v1/uploaded-images 요청 시 사용.
    """
    file = serializers.ImageField(write_only=True)

    class Meta:
        model = UploadedImage
        fields = ['file']

    def validate_file(self, value):
        """업로드된 이미지 파일 유효성 검사."""
        from .constants import ImageConfig

        if value.size > ImageConfig.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise serializers.ValidationError(f'파일 크기는 {ImageConfig.MAX_FILE_SIZE_MB}MB 이하여야 합니다.')

        if value.content_type not in ImageConfig.ALLOWED_CONTENT_TYPES:
            raise serializers.ValidationError('JPG, PNG, WEBP 파일만 업로드 가능합니다.')

        return value

    def create(self, validated_data):
        """업로드된 이미지의 메타데이터를 DB에 저장."""
        file = validated_data['file']
        request = self.context.get('request')

        user = None
        if request and request.user.is_authenticated:
            user = request.user

        uploaded_image = UploadedImage.objects.create(
            user=user,
            uploaded_image_url=file,
        )
        return uploaded_image


class BaseUploadedImageSerializer(serializers.ModelSerializer):
    """
    업로드된 이미지 정보 기본 Serializer.
    중복 제거를 위한 베이스 클래스.
    """
    uploaded_image_id = serializers.IntegerField(source='id')
    uploaded_image_url = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%SZ')

    class Meta:
        model = UploadedImage
        fields = ['uploaded_image_id', 'uploaded_image_url', 'created_at']

    def get_uploaded_image_url(self, obj):
        """이미지 파일의 절대 경로(URL)를 반환."""
        if obj.uploaded_image_url:
            return obj.uploaded_image_url.url
        return ''


# 기존 호환성을 위한 alias
UploadedImageResponseSerializer = BaseUploadedImageSerializer


class UploadedImageListSerializer(BaseUploadedImageSerializer):
    """
    업로드 이미지 목록 조회용 Serializer.
    analysis_id를 포함하여 에이전트 채팅 기능 지원.
    """
    analysis_id = serializers.SerializerMethodField()

    class Meta(BaseUploadedImageSerializer.Meta):
        fields = BaseUploadedImageSerializer.Meta.fields + ['analysis_id']

    def get_analysis_id(self, obj):
        """해당 이미지의 최신 분석 ID 반환."""
        # prefetch된 analyses 사용
        analyses = getattr(obj, '_prefetched_objects_cache', {}).get('analyses')
        if analyses is not None:
            valid_analyses = [a for a in analyses if not a.is_deleted]
            if valid_analyses:
                # 최신 분석 반환
                return max(valid_analyses, key=lambda a: a.created_at).id
        else:
            # prefetch 안 된 경우 쿼리 실행
            latest = obj.analyses.filter(is_deleted=False).order_by('-created_at').first()
            if latest:
                return latest.id
        return None


# =============================================================================
# 이미지 분석 요청/응답 Serializers
# =============================================================================

class ImageAnalysisCreateSerializer(serializers.Serializer):
    """이미지 분석 요청 Serializer."""
    uploaded_image_id = serializers.IntegerField()
    uploaded_image_url = serializers.CharField(required=False, allow_blank=True)

    def validate_uploaded_image_id(self, value):
        """입력된 이미지 ID가 유효한지 검사."""
        try:
            UploadedImage.objects.get(id=value, is_deleted=False)
        except UploadedImage.DoesNotExist:
            raise serializers.ValidationError('존재하지 않는 이미지입니다.')
        return value

    def create(self, validated_data):
        """새로운 ImageAnalysis 레코드 생성."""
        uploaded_image_id = validated_data['uploaded_image_id']
        uploaded_image = UploadedImage.objects.get(id=uploaded_image_id)

        analysis = ImageAnalysis.objects.create(
            uploaded_image=uploaded_image,
            image_analysis_status=ImageAnalysis.Status.PENDING,
        )
        return analysis


class ImageAnalysisResponseSerializer(serializers.ModelSerializer):
    """이미지 분석 요청 성공 응답 Serializer."""
    analysis_id = serializers.IntegerField(source='id')
    status = serializers.CharField(source='image_analysis_status')
    polling = serializers.SerializerMethodField()

    class Meta:
        model = ImageAnalysis
        fields = ['analysis_id', 'status', 'polling']

    def get_polling(self, obj):
        """상태 조회 및 결과 조회를 위한 엔드포인트 생성."""
        return {
            'status_url': f'/api/v1/analyses/{obj.id}/status',
            'result_url': f'/api/v1/analyses/{obj.id}',
        }


class ImageAnalysisStatusSerializer(serializers.ModelSerializer):
    """이미지 분석 상태 조회 응답 Serializer."""
    analysis_id = serializers.IntegerField(source='id')
    status = serializers.CharField(source='image_analysis_status')
    progress = serializers.IntegerField(default=0)
    updated_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%SZ')

    class Meta:
        model = ImageAnalysis
        fields = ['analysis_id', 'status', 'progress', 'updated_at']


# =============================================================================
# 상품 관련 Serializers
# =============================================================================

class SizeOptionSerializer(serializers.Serializer):
    """
    사이즈 옵션 Serializer.
    N+1 쿼리 해결: View에서 prefetch된 selections 사용.
    """
    size_code_id = serializers.IntegerField(source='id')
    size_value = serializers.CharField()
    inventory = serializers.SerializerMethodField()
    selected_product_id = serializers.SerializerMethodField()

    def _get_selected_product(self, size_code):
        """prefetch된 selections에서 SelectedProduct 조회."""
        # prefetch된 selections 사용 (N+1 해결)
        selections = getattr(size_code, '_prefetched_objects_cache', {}).get('selections')
        if selections is not None:
            for selection in selections:
                if not selection.is_deleted:
                    return selection
            return None
        else:
            # prefetch 안 된 경우 (fallback)
            return SelectedProduct.objects.filter(
                product=size_code.product,
                size_code=size_code,
                is_deleted=False
            ).first()

    def get_inventory(self, obj):
        """해당 사이즈의 재고 조회."""
        selected = self._get_selected_product(obj)
        return selected.selected_product_inventory if selected else 0

    def get_selected_product_id(self, obj):
        """해당 사이즈의 SelectedProduct ID 조회."""
        selected = self._get_selected_product(obj)
        return selected.id if selected else None


class ProductSerializer(serializers.ModelSerializer):
    """상품 정보 Serializer."""
    image_url = serializers.CharField(source='product_image_url')
    sizes = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['id', 'brand_name', 'product_name', 'selling_price', 'image_url', 'product_url', 'sizes']

    def get_sizes(self, obj):
        """상품의 사이즈 옵션 목록 반환."""
        # prefetch된 size_codes 사용
        size_codes = getattr(obj, '_prefetched_objects_cache', {}).get('size_codes')
        if size_codes is not None:
            valid_sizes = [sc for sc in size_codes if not sc.is_deleted]
        else:
            valid_sizes = SizeCode.objects.filter(product=obj, is_deleted=False)
        return SizeOptionSerializer(valid_sizes, many=True).data


class MatchSerializer(serializers.ModelSerializer):
    """검출 객체-상품 매핑 Serializer."""
    product_id = serializers.IntegerField(source='product.id')
    product = ProductSerializer()

    class Meta:
        model = ObjectProductMapping
        fields = ['product_id', 'product']


# =============================================================================
# 검출 객체 Serializers (Base 클래스로 중복 제거)
# =============================================================================

class BaseDetectedObjectSerializer(BboxSerializerMixin, ConfidenceScoreMixin, serializers.ModelSerializer):
    """
    검출된 객체 기본 Serializer.
    공통 필드와 메서드를 정의하는 베이스 클래스.
    """
    detected_object_id = serializers.IntegerField(source='id')
    category_name = serializers.CharField(source='object_category')
    confidence_score = serializers.SerializerMethodField()
    bbox = serializers.SerializerMethodField()
    match = serializers.SerializerMethodField()

    class Meta:
        model = DetectedObject
        fields = ['detected_object_id', 'category_name', 'confidence_score', 'bbox', 'match']

    def _get_best_mapping(self, obj):
        """가장 높은 신뢰도의 매핑 반환."""
        mappings = getattr(obj, '_prefetched_objects_cache', {}).get('product_mappings')
        if mappings is not None:
            valid_mappings = [m for m in mappings if not m.is_deleted]
            if valid_mappings:
                return max(valid_mappings, key=lambda m: m.confidence_score)
        else:
            return obj.product_mappings.filter(is_deleted=False).order_by('-confidence_score').first()
        return None

    def get_match(self, obj):
        """가장 높은 신뢰도의 매칭 상품 반환."""
        mapping = self._get_best_mapping(obj)
        if mapping:
            return MatchSerializer(mapping).data
        return None


# 분석 결과 조회용 (기본 버전)
class DetectedObjectResultSerializer(BaseDetectedObjectSerializer):
    """GET /api/v1/analyses/{analysis_id} 응답용."""
    pass


# =============================================================================
# 이미지 분석 결과 Serializers
# =============================================================================

class UploadedImageInfoSerializer(serializers.ModelSerializer):
    """업로드된 이미지 정보 (결과 조회용)."""
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
    이미지 분석 결과 조회 응답 Serializer.
    GET /api/v1/analyses/{analysis_id}
    """
    analysis_id = serializers.IntegerField(source='id')
    uploaded_image = UploadedImageInfoSerializer()
    status = serializers.CharField(source='image_analysis_status')
    items = serializers.SerializerMethodField()

    class Meta:
        model = ImageAnalysis
        fields = ['analysis_id', 'uploaded_image', 'status', 'items']

    def get_items(self, obj):
        """분석된 이미지의 검출된 객체 목록 반환."""
        detected_objects = obj.uploaded_image.detected_objects.filter(is_deleted=False)
        return DetectedObjectResultSerializer(detected_objects, many=True).data


# =============================================================================
# 자연어 기반 결과 수정 (API 6) Serializers
# =============================================================================

class AnalysisRefineRequestSerializer(serializers.Serializer):
    """자연어 기반 결과 수정 요청 Serializer."""
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
    """API 6 응답용 이미지 정보."""
    uploaded_image_id = serializers.IntegerField(source='id')
    uploaded_image_url = serializers.SerializerMethodField()

    class Meta:
        model = UploadedImage
        fields = ['uploaded_image_id', 'uploaded_image_url']

    def get_uploaded_image_url(self, obj):
        if obj.uploaded_image_url:
            return obj.uploaded_image_url.url
        return ''


class AnalysisRefineItemSerializer(BaseDetectedObjectSerializer):
    """
    API 6 응답용 검출 객체 Serializer.
    sizes 정보를 포함한 확장 버전.
    """

    def get_match(self, obj):
        """매칭 상품 + sizes 정보 반환."""
        mapping = self._get_best_mapping(obj)
        if not mapping:
            return None

        product = mapping.product

        # 사이즈 목록 조회 (prefetch 활용)
        sizes = self._build_sizes_list(product)

        return {
            'product_id': product.id,
            'product': {
                'id': product.id,
                'brand_name': product.brand_name,
                'product_name': product.product_name,
                'selling_price': product.selling_price,
                'image_url': product.product_image_url,
                'product_url': product.product_url,
                'sizes': sizes,
            }
        }

    def _build_sizes_list(self, product):
        """상품의 사이즈 목록 생성."""
        sizes = []
        # prefetch된 size_codes 사용
        size_codes = getattr(product, '_prefetched_objects_cache', {}).get('size_codes')
        if size_codes is not None:
            valid_codes = [sc for sc in size_codes if not sc.is_deleted]
        else:
            valid_codes = product.size_codes.filter(is_deleted=False)

        for size_code in valid_codes:
            # prefetch된 selections 사용
            selections = getattr(size_code, '_prefetched_objects_cache', {}).get('selections')
            if selections is not None:
                selected = next((s for s in selections if not s.is_deleted), None)
            else:
                selected = size_code.selections.filter(is_deleted=False).first()

            sizes.append({
                'size_code_id': size_code.id,
                'size_value': size_code.size_value,
                'inventory': selected.selected_product_inventory if selected else 0,
                'selected_product_id': selected.id if selected else None,
            })
        return sizes


class AnalysisRefineResponseSerializer(serializers.ModelSerializer):
    """자연어 기반 결과 수정 응답 Serializer."""
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
# 통합 히스토리 조회 (API 10) Serializers
# =============================================================================

class FittingInfoSerializer(serializers.Serializer):
    """피팅 이미지 정보 Serializer."""
    fitting_image_id = serializers.IntegerField()
    fitting_image_url = serializers.CharField()


class HistoryMatchSerializer(serializers.Serializer):
    """통합 히스토리 조회용 매칭 정보 Serializer."""
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
        """해당 상품에 대한 피팅 이미지 조회."""
        from fittings.models import FittingImage

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


class HistoryItemSerializer(BaseDetectedObjectSerializer):
    """통합 히스토리 조회용 검출 객체 Serializer (피팅 정보 포함)."""

    def get_match(self, obj):
        """매칭된 상품 + 피팅 정보 반환."""
        from fittings.models import FittingImage

        mapping = self._get_best_mapping(obj)
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

        # 사이즈 목록
        sizes = self._build_sizes_list(product)

        return {
            'product_id': product.id,
            'product': {
                'id': product.id,
                'brand_name': product.brand_name,
                'product_name': product.product_name,
                'selling_price': product.selling_price,
                'image_url': product.product_image_url,
                'product_url': product.product_url,
                'sizes': sizes,
            },
            'fitting': fitting_data,
        }

    def _build_sizes_list(self, product):
        """상품의 사이즈 목록 생성."""
        sizes = []
        for size_code in product.size_codes.filter(is_deleted=False):
            selected = size_code.selections.filter(is_deleted=False).first()
            sizes.append({
                'size_code_id': size_code.id,
                'size_value': size_code.size_value,
                'inventory': selected.selected_product_inventory if selected else 0,
                'selected_product_id': selected.id if selected else None,
            })
        return sizes


class UploadedImageHistoryResponseSerializer(serializers.Serializer):
    """통합 히스토리 조회 응답 Serializer."""
    items = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.detected_objects = kwargs.pop('detected_objects', [])
        super().__init__(*args, **kwargs)

    def get_items(self, obj):
        return HistoryItemSerializer(self.detected_objects, many=True).data


# =============================================================================
# Feed Serializers (Pinterest 스타일 피드용)
# =============================================================================

class FeedUserSerializer(serializers.Serializer):
    """피드 아이템의 사용자 정보 Serializer."""
    id = serializers.IntegerField()
    username = serializers.CharField()


class FeedDetectedObjectSerializer(serializers.Serializer):
    """피드용 검출 객체 Serializer (간소화 버전)."""
    id = serializers.IntegerField()
    category = serializers.CharField(source='object_category')
    cropped_image_url = serializers.CharField(allow_null=True, required=False)
    matched_product = serializers.SerializerMethodField()

    def get_matched_product(self, obj):
        """매칭된 상품 정보 반환 (최상위 1개)."""
        # prefetch된 데이터 사용
        mappings = getattr(obj, '_prefetched_objects_cache', {}).get('product_mappings')
        if mappings is not None:
            valid_mappings = [m for m in mappings if not m.is_deleted]
            if valid_mappings:
                best = max(valid_mappings, key=lambda m: m.confidence_score)
                product = best.product
                return {
                    'id': product.id,
                    'brand_name': product.brand_name,
                    'product_name': product.product_name,
                    'selling_price': product.selling_price,
                    'image_url': product.product_image_url,
                    'product_url': product.product_url,
                }
        else:
            mapping = obj.product_mappings.filter(is_deleted=False).order_by('-confidence_score').first()
            if mapping:
                product = mapping.product
                return {
                    'id': product.id,
                    'brand_name': product.brand_name,
                    'product_name': product.product_name,
                    'selling_price': product.selling_price,
                    'image_url': product.product_image_url,
                    'product_url': product.product_url,
                }
        return None


class FeedItemSerializer(serializers.ModelSerializer):
    """피드 아이템 Serializer (업로드 이미지 + 검출 객체들)."""
    user = serializers.SerializerMethodField()
    detected_objects = serializers.SerializerMethodField()
    analysis_status = serializers.SerializerMethodField()

    class Meta:
        model = UploadedImage
        fields = ['id', 'uploaded_image_url', 'user', 'created_at', 'is_public', 'detected_objects', 'analysis_status']

    def get_user(self, obj):
        if obj.user:
            return {
                'id': obj.user.id,
                'username': obj.user.username,
            }
        return None

    def get_analysis_status(self, obj):
        """분석 상태 반환."""
        analysis = getattr(obj, '_prefetched_analysis', None)
        if analysis is None:
            analysis = obj.analyses.filter(is_deleted=False).order_by('-created_at').first()
        if analysis:
            return analysis.image_analysis_status
        return None

    def get_detected_objects(self, obj):
        """검출된 객체들 반환."""
        # prefetch된 detected_objects 사용
        detected_objects = getattr(obj, '_prefetched_detected_objects', None)
        if detected_objects is None:
            detected_objects = DetectedObject.objects.filter(
                uploaded_image=obj,
                is_deleted=False
            ).prefetch_related('product_mappings', 'product_mappings__product')
        return FeedDetectedObjectSerializer(detected_objects, many=True).data
