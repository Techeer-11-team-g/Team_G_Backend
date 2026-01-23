"""
공통 Serializer 유틸리티.

여러 앱에서 사용되는 Serializer 믹스인과 기능을 제공합니다.
"""

from rest_framework import serializers


class PrefetchMixin:
    """
    Serializer에 prefetch_related/select_related 설정을 자동 적용하는 믹스인.

    Meta 클래스에 prefetch_related와 select_related를 정의하면
    QuerySet에 자동으로 적용됩니다.

    Usage:
        class MySerializer(PrefetchMixin, serializers.ModelSerializer):
            class Meta:
                model = MyModel
                fields = ['id', 'name', 'related_items']
                prefetch_related = ['related_items', 'tags']
                select_related = ['author']

        # In view:
        queryset = MySerializer.setup_eager_loading(MyModel.objects.all())
        serializer = MySerializer(queryset, many=True)
    """

    @classmethod
    def setup_eager_loading(cls, queryset):
        """
        Serializer의 Meta 클래스에 정의된 prefetch/select 설정을 QuerySet에 적용.

        Args:
            queryset: 기본 QuerySet

        Returns:
            최적화된 QuerySet
        """
        meta = getattr(cls, 'Meta', None)
        if meta is None:
            return queryset

        # select_related 적용 (1:1, N:1 관계)
        select_related = getattr(meta, 'select_related', None)
        if select_related:
            queryset = queryset.select_related(*select_related)

        # prefetch_related 적용 (1:N, N:M 관계)
        prefetch_related = getattr(meta, 'prefetch_related', None)
        if prefetch_related:
            queryset = queryset.prefetch_related(*prefetch_related)

        return queryset


class NestedPrefetchMixin(PrefetchMixin):
    """
    중첩 Serializer의 prefetch 설정도 자동 적용하는 확장 믹스인.

    중첩된 Serializer가 PrefetchMixin을 사용하는 경우,
    해당 설정도 함께 적용합니다.

    Usage:
        class ItemSerializer(PrefetchMixin, serializers.ModelSerializer):
            class Meta:
                model = Item
                fields = ['id', 'name']
                select_related = ['category']

        class OrderSerializer(NestedPrefetchMixin, serializers.ModelSerializer):
            items = ItemSerializer(many=True)

            class Meta:
                model = Order
                fields = ['id', 'items']
                prefetch_related = ['items']

        # items의 category도 자동으로 prefetch됨
        queryset = OrderSerializer.setup_eager_loading(Order.objects.all())
    """

    @classmethod
    def setup_eager_loading(cls, queryset):
        """부모 클래스 호출 후 중첩 Serializer 설정 적용."""
        queryset = super().setup_eager_loading(queryset)

        # 필드 정의에서 중첩 Serializer 찾기
        for field_name, field in cls().fields.items():
            nested_serializer = getattr(field, 'child', field)

            # 중첩 Serializer가 PrefetchMixin을 사용하는지 확인
            if hasattr(nested_serializer, 'setup_eager_loading'):
                nested_meta = getattr(type(nested_serializer), 'Meta', None)
                if nested_meta:
                    # 중첩 Serializer의 select_related를 Prefetch로 변환
                    nested_select = getattr(nested_meta, 'select_related', None)
                    if nested_select:
                        from django.db.models import Prefetch
                        prefetch_path = f'{field_name}__'
                        for relation in nested_select:
                            queryset = queryset.prefetch_related(
                                f'{prefetch_path}{relation}'
                            )

        return queryset


class ReadOnlyFieldsMixin:
    """
    지정된 필드를 읽기 전용으로 설정하는 믹스인.

    Usage:
        class UserSerializer(ReadOnlyFieldsMixin, serializers.ModelSerializer):
            class Meta:
                model = User
                fields = ['id', 'username', 'email', 'created_at']
                read_only_auto_fields = ['id', 'created_at']
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        meta = getattr(self, 'Meta', None)
        if meta:
            read_only_fields = getattr(meta, 'read_only_auto_fields', [])
            for field_name in read_only_fields:
                if field_name in self.fields:
                    self.fields[field_name].read_only = True


class DynamicFieldsMixin:
    """
    요청 시 필드를 동적으로 선택할 수 있게 하는 믹스인.

    Usage:
        serializer = MySerializer(queryset, fields=['id', 'name'])

        # 또는 context로 전달
        serializer = MySerializer(queryset, context={'fields': ['id', 'name']})
    """

    def __init__(self, *args, **kwargs):
        fields = kwargs.pop('fields', None)
        super().__init__(*args, **kwargs)

        if fields is None:
            fields = self.context.get('fields')

        if fields is not None:
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)
