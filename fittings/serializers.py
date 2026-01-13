from rest_framework import serializers
from .models import FittingImage

class FittingImageSerializer(serializers.ModelSerializer):
    fitting_image_id = serializers.IntegerField(source='id', read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    polling = serializers.SerializerMethodField(read_only=True)

    # 입력 전용 필드들 (write_only=True)
    # 프론트에서 'product'라는 키로 ID를 보내면 모델의 product 외래키와 연결됩니다.
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), 
        write_only=True
    )
    user_image = serializers.PrimaryKeyRelatedField(
        queryset=UserImage.objects.all(), 
        write_only=True
    )

    class Meta:
        model = FittingImage
        fields = [
            'fitting_image_id', 'status', 'fitting_image_url', 
            'polling', 'product', 'user_image'
        ]

    def get_status(self, obj):
        return obj.fitting_image_status.upper()

    def get_polling(self, obj):
        return {
            "status_url": f"/api/v1/fitting-images/{obj.id}/status",
            "result_url": f"/api/v1/fitting-images/{obj.id}"
        }
class FittingStatusSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%S")

    class Meta:
        model = FittingImage
        fields = ['status', 'progress', 'updated_at']

    def get_status(self, obj):
        return obj.fitting_image_status.upper()

    def get_progress(self, obj):
        if obj.fitting_image_status == FittingImage.Status.RUNNING:
            return 40
        elif obj.fitting_image_status == FittingImage.Status.DONE:
            return 100
        elif obj.fitting_image_status == FittingImage.Status.FAILED:
            return 0
        return 0 