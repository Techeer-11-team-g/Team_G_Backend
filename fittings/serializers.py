from rest_framework import serializers
from .models import FittingImage

class FittingImageSerializer(serializers.ModelSerializer):
    # 명세서의 필드명과 일치시키기 위해 추가 필드 정의
    fitting_image_id = serializers.IntegerField(source='id', read_only=True)
    status = serializers.SerializerMethodField()
    polling = serializers.SerializerMethodField()

    class Meta:
        model = FittingImage
        fields = ['fitting_image_id', 'status', 'fitting_image_url', 'polling']

    # 모델의 소문자 상태값을 명세서의 대문자 규격으로 변환
    def get_status(self, obj):
        return obj.fitting_image_status.upper()

    # 명세서의 polling 경로 구조를 동적으로 생성
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