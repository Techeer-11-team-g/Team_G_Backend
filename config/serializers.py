"""
기본 Serializer 클래스.

모든 앱에서 공통으로 사용할 수 있는 시리얼라이저 기본 클래스입니다.
기존 코드는 그대로 유지하며, 새 시리얼라이저 작성 시 상속받아 사용합니다.

Usage:
    from config.serializers import BaseModelSerializer

    class ProductSerializer(BaseModelSerializer):
        class Meta(BaseModelSerializer.Meta):
            model = Product
            fields = ['id', 'name', 'price', ...]
"""

from rest_framework import serializers


class BaseModelSerializer(serializers.ModelSerializer):
    """
    기본 모델 시리얼라이저.

    공통 읽기 전용 필드를 자동으로 설정하고,
    soft delete 관련 필드를 기본적으로 제외합니다.
    """

    class Meta:
        # 하위 클래스에서 model과 fields 지정 필수
        model = None
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']

    # soft delete 필드는 기본적으로 제외
    _exclude_soft_delete = True

    def get_fields(self):
        """soft delete 필드 자동 제외."""
        fields = super().get_fields()

        if self._exclude_soft_delete:
            for field_name in ['is_deleted', 'deleted_at']:
                fields.pop(field_name, None)

        return fields


class BaseListSerializer(BaseModelSerializer):
    """
    목록 조회용 시리얼라이저.

    간략한 정보만 반환합니다.
    """
    pass


class BaseDetailSerializer(BaseModelSerializer):
    """
    상세 조회용 시리얼라이저.

    모든 정보를 반환합니다.
    """
    pass


class BaseCreateSerializer(BaseModelSerializer):
    """
    생성용 시리얼라이저.

    생성 시 필요하지 않은 필드를 자동으로 제외합니다.
    """

    class Meta(BaseModelSerializer.Meta):
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_fields(self):
        fields = super().get_fields()

        # 생성 시 제외할 필드
        for field_name in ['id', 'created_at', 'updated_at', 'is_deleted', 'deleted_at']:
            fields.pop(field_name, None)

        return fields


class BaseUpdateSerializer(BaseModelSerializer):
    """
    수정용 시리얼라이저.

    부분 수정을 지원합니다.
    """

    def __init__(self, *args, **kwargs):
        # partial=True가 기본값
        kwargs.setdefault('partial', True)
        super().__init__(*args, **kwargs)


class TimestampMixin(serializers.Serializer):
    """
    타임스탬프 필드 믹스인.

    created_at, updated_at 필드를 ISO 8601 형식으로 반환합니다.
    """
    created_at = serializers.DateTimeField(read_only=True, format='%Y-%m-%dT%H:%M:%S.%fZ')
    updated_at = serializers.DateTimeField(read_only=True, format='%Y-%m-%dT%H:%M:%S.%fZ')


class PaginatedResponseSerializer(serializers.Serializer):
    """
    페이지네이션 응답 시리얼라이저.

    커서 기반 페이지네이션 응답 형식입니다.
    """
    items = serializers.ListField(child=serializers.DictField())
    next_cursor = serializers.CharField(allow_null=True, required=False)
    has_next = serializers.BooleanField(required=False)
    total_count = serializers.IntegerField(required=False)


class ErrorResponseSerializer(serializers.Serializer):
    """
    에러 응답 시리얼라이저.

    표준 에러 응답 형식입니다.
    """
    error = serializers.CharField()
    message = serializers.CharField()


class SuccessResponseSerializer(serializers.Serializer):
    """
    성공 응답 시리얼라이저.

    단순 성공 응답용입니다.
    """
    success = serializers.BooleanField(default=True)
    message = serializers.CharField(required=False)
