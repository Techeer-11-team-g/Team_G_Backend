from django.db import models
from django.conf import settings


class UploadedImage(models.Model):
    """
    업로드된 이미지 테이블
    ERD: uploaded_image
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_images',
        db_column='user_id',
        verbose_name='사용자 아이디',
    )

    uploaded_image_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name='업로드한 이미지 URL',
        help_text='GCS에 저장된 원본 이미지 URL',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 일자',
    )

    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    is_public = models.BooleanField(
        default=False,
        verbose_name='공개 여부',
        help_text='True이면 피드에 공개됨',
    )

    class Meta:
        db_table = 'uploaded_image'
        ordering = ['-created_at']
        verbose_name = '업로드된 이미지'
        verbose_name_plural = '업로드된 이미지 목록'

    def __str__(self):
        return f"UploadedImage #{self.pk}"


class ImageAnalysis(models.Model):
    """
    이미지 분석 테이블
    ERD: image_analysis
    이미지 분석 작업의 상태 및 결과 관리
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', '대기 중'
        RUNNING = 'RUNNING', '분석 중'
        DONE = 'DONE', '완료'
        FAILED = 'FAILED', '실패'

    uploaded_image = models.ForeignKey(
        UploadedImage,
        on_delete=models.CASCADE,
        related_name='analyses',
        db_column='uploaded_image_id',
        verbose_name='업로드된 이미지',
    )

    image_analysis_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='분석 상태',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 일자',
    )

    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    class Meta:
        db_table = 'image_analysis'
        ordering = ['-created_at']
        verbose_name = '이미지 분석'
        verbose_name_plural = '이미지 분석 목록'

    def __str__(self):
        return f"Analysis #{self.pk} - {self.image_analysis_status}"


class DetectedObject(models.Model):
    """
    검출된 객체 테이블
    ERD: detected_object
    이미지에서 검출된 패션 아이템 (상의, 하의, 신발, 가방 등)
    """
    uploaded_image = models.ForeignKey(
        UploadedImage,
        on_delete=models.CASCADE,
        related_name='detected_objects',
        db_column='uploaded_image_id',
        verbose_name='업로드된 이미지',
    )

    bbox_x1 = models.FloatField(
        default=0.0,
        verbose_name='Bounding Box X1',
        help_text='정규화된 좌표 (0~1)',
    )

    bbox_y1 = models.FloatField(
        default=0.0,
        verbose_name='Bounding Box Y1',
        help_text='정규화된 좌표 (0~1)',
    )

    bbox_x2 = models.FloatField(
        default=0.0,
        verbose_name='Bounding Box X2',
        help_text='정규화된 좌표 (0~1)',
    )

    bbox_y2 = models.FloatField(
        default=0.0,
        verbose_name='Bounding Box Y2',
        help_text='정규화된 좌표 (0~1)',
    )

    object_category = models.CharField(
        max_length=100,
        verbose_name='객체 카테고리',
        help_text='검출된 객체의 카테고리 (상의, 하의, 신발 등)',
    )

    cropped_image_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name='크롭 이미지 URL',
        help_text='GCS에 저장된 크롭된 이미지 URL',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 일자',
    )

    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    class Meta:
        db_table = 'detected_object'
        verbose_name = '검출된 객체'
        verbose_name_plural = '검출된 객체 목록'

    def __str__(self):
        return f"DetectedObject #{self.pk} - {self.object_category}"

    @property
    def bbox(self):
        """API 응답용 bbox 딕셔너리 반환"""
        return {
            'x1': round(self.bbox_x1, 2),
            'y1': round(self.bbox_y1, 2),
            'x2': round(self.bbox_x2, 2),
            'y2': round(self.bbox_y2, 2),
        }


class ObjectProductMapping(models.Model):
    """
    검출 객체-상품 매핑 테이블
    ERD: object_product_mapping
    검출된 객체와 유사 상품 간의 매핑 (OpenSearch k-NN 검색 결과)
    """
    detected_object = models.ForeignKey(
        DetectedObject,
        on_delete=models.CASCADE,
        related_name='product_mappings',
        db_column='object_id',
        verbose_name='검출된 객체',
    )

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='object_mappings',
        db_column='product_id',
        verbose_name='상품',
    )

    confidence_score = models.FloatField(
        default=0.0,
        verbose_name='신뢰도 점수',
        help_text='코사인 유사도 (0~1)',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )

    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    class Meta:
        db_table = 'object_product_mapping'
        verbose_name = '객체-상품 매핑'
        verbose_name_plural = '객체-상품 매핑 목록'

    def __str__(self):
        return f"Mapping #{self.pk} - {self.detected_object} -> {self.product}"


class SelectedProduct(models.Model):
    """
    선택된 상품 테이블
    ERD: selected_product
    사용자가 선택한 상품 (특정 사이즈)
    """
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='selections',
        db_column='product_id',
        verbose_name='상품',
    )

    size_code = models.ForeignKey(
        'products.SizeCode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='selections',
        db_column='size_code_id',
        verbose_name='사이즈 코드',
    )

    selected_product_inventory = models.PositiveIntegerField(
        default=0,
        verbose_name='선택 상품 재고',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 일자',
    )

    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    class Meta:
        db_table = 'selected_product'
        verbose_name = '선택된 상품'
        verbose_name_plural = '선택된 상품 목록'

    def __str__(self):
        return f"Selected #{self.pk} - {self.product}"
