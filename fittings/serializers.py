"""
fittings/serializers.py - 가상 피팅 Serializers

이 모듈은 가상 피팅 기능에 필요한 Serializer들을 정의합니다.

주요 기능:
    - 사용자 이미지 업로드 및 최적화
    - 가상 피팅 요청 처리
    - 피팅 상태 및 결과 조회

Serializers:
    - UserImageUploadSerializer: 사용자 전신 이미지 업로드
    - FittingImageSerializer: 가상 피팅 요청
    - FittingStatusSerializer: 피팅 상태 조회
    - FittingResultSerializer: 피팅 결과 조회
"""

import logging
import re
from io import BytesIO

from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db.models import Q
from PIL import Image, ImageOps
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from products.models import Product
from .models import FittingImage, UserImage

logger = logging.getLogger(__name__)


# =============================================================================
# 이미지 최적화 설정
# =============================================================================
IMAGE_MAX_WIDTH = 768       # API 권장 최대 너비
IMAGE_MAX_HEIGHT = 1024     # API 권장 최대 높이
JPEG_QUALITY = 85           # JPEG 압축 품질 (1-100)


# =============================================================================
# 이미지 처리 유틸리티 함수
# =============================================================================

def _get_jpeg_filename(original_name: str) -> str:
    """
    파일명을 .jpg 확장자로 변환합니다.
    
    Args:
        original_name: 원본 파일명
        
    Returns:
        str: .jpg 확장자가 붙은 파일명
    """
    if '.' in original_name:
        name_without_ext = original_name.rsplit('.', 1)[0]
    else:
        name_without_ext = original_name
    return f"{name_without_ext}.jpg"


def _convert_to_jpeg(img, original_name: str, original_size: int, original_dimensions: tuple):
    """
    PIL Image를 JPEG 형식의 InMemoryUploadedFile로 변환합니다.
    
    Args:
        img: PIL Image 객체
        original_name: 원본 파일명
        original_size: 원본 파일 크기 (bytes)
        original_dimensions: 원본 이미지 크기 (width, height)
    
    Returns:
        InMemoryUploadedFile: JPEG로 변환된 이미지 파일
    """
    # 투명도가 있는 이미지를 RGB로 변환 (JPEG 저장을 위해)
    if img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGB')
    
    # JPEG로 압축
    buffer = BytesIO()
    img.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    buffer.seek(0)
    
    optimized_file = InMemoryUploadedFile(
        file=buffer,
        field_name='file',
        name=_get_jpeg_filename(original_name),
        content_type='image/jpeg',
        size=buffer.getbuffer().nbytes,
        charset=None
    )
    
    logger.info(
        f"이미지 최적화 완료: {original_dimensions} -> {img.size}, "
        f"{original_size:,} bytes -> {buffer.getbuffer().nbytes:,} bytes"
    )
    return optimized_file


def optimize_image_for_fitting(image_file):
    """
    가상 피팅 API 최적화를 위한 이미지 리사이즈 및 압축을 수행합니다.
    
    처리 과정:
        1. EXIF 회전 정보 적용 (사진 방향 보정)
        2. 768x1024 이하로 리사이즈 (비율 유지)
        3. JPEG 형식으로 압축 (Quality 85)
    
    Args:
        image_file: 업로드된 이미지 파일
        
    Returns:
        InMemoryUploadedFile: 최적화된 이미지 파일
        
    Note:
        최적화 실패 시 원본 파일을 그대로 반환합니다.
    """
    try:
        img = Image.open(image_file)
        original_size = image_file.size
        original_dimensions = img.size
        
        # EXIF 회전 정보 적용 (사진 방향 보정)
        img = ImageOps.exif_transpose(img)
        
        # 이미 작은 이미지는 리사이즈 불필요 (JPEG 압축만 적용)
        if img.width <= IMAGE_MAX_WIDTH and img.height <= IMAGE_MAX_HEIGHT:
            return _convert_to_jpeg(img, image_file.name, original_size, original_dimensions)
        
        # 비율 유지하며 리사이즈
        img.thumbnail((IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT), Image.LANCZOS)
        
        return _convert_to_jpeg(img, image_file.name, original_size, original_dimensions)
        
    except Exception as e:
        logger.warning(f"이미지 최적화 실패, 원본 사용: {e}")
        image_file.seek(0)
        return image_file


# =============================================================================
# Serializers
# =============================================================================

class UserImageUploadSerializer(serializers.ModelSerializer):
    """
    사용자 전신 이미지 업로드 Serializer
    
    Endpoint: POST /api/v1/user-images
    
    기능:
        - 사용자 전신 이미지 업로드
        - 이미지 자동 최적화 (768x1024 리사이즈 + JPEG 압축)
        - GCS에 저장 후 URL 반환
    
    Request:
        - file (ImageField): 이미지 파일 (JPG, PNG, WEBP / 최대 10MB)
    
    Response:
        - user_image_id (int): 생성된 이미지 ID
        - user_image_url (str): 저장된 이미지 URL
        - created_at (datetime): 생성 일시
    """
    
    # === Response 필드 ===
    user_image_id = serializers.IntegerField(source='id', read_only=True)
    user_image_url = serializers.SerializerMethodField(read_only=True)
    created_at = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", read_only=True)

    # === Request 필드 ===
    file = serializers.ImageField(write_only=True)

    class Meta:
        model = UserImage
        fields = ['user_image_id', 'user_image_url', 'created_at', 'file']

    @extend_schema_field(OpenApiTypes.URI)
    def get_user_image_url(self, obj) -> str:
        """저장된 이미지의 URL을 반환합니다."""
        if obj.user_image_url:
            # ImageField인 경우 .url 속성 사용
            if hasattr(obj.user_image_url, 'url'):
                return obj.user_image_url.url
            return str(obj.user_image_url)
        return ''

    def validate_file(self, value):
        """
        업로드 파일 유효성을 검사합니다.
        
        검사 항목:
            - 파일 크기: 최대 10MB
            - 파일 형식: JPG, PNG, WEBP만 허용
        """
        # 파일 크기 제한 (10MB)
        max_size = 10 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError('파일 크기는 10MB 이하여야 합니다.')

        # 허용된 파일 형식
        allowed_types = ['image/jpeg', 'image/png', 'image/webp']
        if value.content_type not in allowed_types:
            raise serializers.ValidationError('JPG, PNG, WEBP 파일만 업로드 가능합니다.')

        return value

    def create(self, validated_data):
        """
        사용자 이미지를 생성합니다.
        
        처리 과정:
            1. 업로드된 이미지 최적화
            2. DB에 UserImage 레코드 생성
            3. 이미지 파일 저장 (GCS 또는 로컬)
        """
        file = validated_data.pop('file')
        user = self.context.get('request').user  # JWT 인증된 유저

        # 이미지 최적화 (768x1024 리사이즈 + JPEG 압축)
        optimized_file = optimize_image_for_fitting(file)

        user_image = UserImage.objects.create(
            user=user,
            user_image_url=optimized_file 
        )
        return user_image


class FittingImageSerializer(serializers.ModelSerializer):
    """
    가상 피팅 요청 Serializer
    
    Endpoint: POST /api/v1/fitting-images
    
    기능:
        - 사용자 이미지 + 상품 조합으로 가상 피팅 요청
        - 기존 결과가 있으면 캐싱된 결과 반환
        - Celery 비동기 태스크로 피팅 처리
    
    Request:
        - product_id (int): 피팅할 상품 ID
        - user_image_url (str): 이미 업로드된 사용자 이미지 URL
    
    Response:
        - fitting_image_id (int): 피팅 요청 ID
        - fitting_image_status (str): 피팅 상태 (PENDING/RUNNING/DONE/FAILED)
        - fitting_image_url (str): 피팅 결과 이미지 URL
        - polling (dict): 폴링용 API URL
        - completed_at (datetime): 완료 일시
    """
    
    # === Response 필드 (read_only) ===
    fitting_image_id = serializers.IntegerField(source='id', read_only=True)
    fitting_image_status = serializers.CharField(read_only=True)
    fitting_image_url = serializers.URLField(read_only=True)
    polling = serializers.SerializerMethodField(read_only=True)
    completed_at = serializers.DateTimeField(
        source='updated_at',
        format="%Y-%m-%dT%H:%M:%SZ",
        read_only=True
    )

    # === Request 필드 (write_only) ===
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

    @extend_schema_field({'type': 'object', 'properties': {
        'status_url': {'type': 'string'},
        'result_url': {'type': 'string'},
    }})
    def get_polling(self, obj) -> dict:
        """클라이언트 폴링용 API URL을 반환합니다."""
        return {
            "status_url": f"/api/v1/fitting-images/{obj.id}/status",
            "result_url": f"/api/v1/fitting-images/{obj.id}"
        }

    def validate_user_image_url(self, value):
        """
        사용자 이미지 URL을 검증하고 UserImage 객체를 반환합니다.

        지원하는 URL 형식:
            - GCS URL: https://storage.googleapis.com/{bucket}/{path}
            - 상대 경로: /media/user-images/...
            - 전체 URL: https://example.com/media/...

        Returns:
            UserImage: 검증된 사용자 이미지 객체

        Raises:
            ValidationError: 존재하지 않는 URL인 경우
        """
        # 쿼리 파라미터 제거 (?v=..., ?t=... 등 캐시 버스터)
        value = value.split('?')[0]
        search_value = value

        # GCS URL에서 경로 추출
        gcs_pattern = r'https://storage\.googleapis\.com/[^/]+/(.+)'
        gcs_match = re.match(gcs_pattern, value)
        
        if gcs_match:
            search_value = gcs_match.group(1)
        elif '/media/' in value:
            search_value = value.split('/media/')[-1]
        elif value.startswith('/'):
            search_value = value.lstrip('/')

        # DB에서 UserImage 조회 (복합 조건으로 유연하게 검색)
        user_image = UserImage.objects.filter(
            Q(user_image_url__exact=value) |
            Q(user_image_url__exact=search_value) |
            Q(user_image_url__endswith=search_value),
            is_deleted=False
        ).first()
        
        if user_image:
            return user_image

        raise serializers.ValidationError(
            '존재하지 않는 사용자 이미지 URL입니다. '
            '먼저 /api/v1/user-images 에서 이미지를 업로드하세요.'
        )

    def create(self, validated_data):
        """FittingImage 레코드를 생성합니다."""
        user_image = validated_data.pop('user_image_url')
        validated_data['user_image'] = user_image
        return super().create(validated_data)


# =============================================================================
# 조회용 Serializers
# =============================================================================

class FittingStatusMixin:
    """
    피팅 상태 조회에 필요한 공통 메서드를 제공하는 Mixin

    제공 메서드:
        - get_fitting_image_status: 상태값을 대문자로 변환
    """

    @extend_schema_field(OpenApiTypes.STR)
    def get_fitting_image_status(self, obj) -> str:
        """피팅 상태값을 대문자로 반환합니다."""
        return obj.fitting_image_status.upper()


class FittingStatusSerializer(FittingStatusMixin, serializers.ModelSerializer):
    """
    가상 피팅 상태 조회 Serializer
    
    Endpoint: GET /api/v1/fitting-images/{fitting_image_id}/status
    
    Response:
        - fitting_image_status (str): 피팅 상태 (PENDING/RUNNING/DONE/FAILED)
        - progress (int): 진행률 (0-100)
        - updated_at (datetime): 최종 업데이트 일시
    """
    fitting_image_status = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ")

    class Meta:
        model = FittingImage
        fields = ['fitting_image_status', 'progress', 'updated_at']

    @extend_schema_field(OpenApiTypes.INT)
    def get_progress(self, obj) -> int:
        """
        피팅 상태에 따른 진행률을 반환합니다.

        Returns:
            int: 진행률 (RUNNING: 40, DONE: 100, 기타: 0)
        """
        status_progress = {
            FittingImage.Status.RUNNING: 40,
            FittingImage.Status.DONE: 100,
        }
        return status_progress.get(obj.fitting_image_status, 0)


class FittingResultSerializer(FittingStatusMixin, serializers.ModelSerializer):
    """
    가상 피팅 결과 조회 Serializer
    
    Endpoint: GET /api/v1/fitting-images/{fitting_image_id}
    
    Response:
        - fitting_image_id (int): 피팅 요청 ID
        - fitting_image_status (str): 피팅 상태
        - fitting_image_url (str): 피팅 결과 이미지 URL
        - completed_at (datetime): 완료 일시
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
