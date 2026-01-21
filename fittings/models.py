"""
fittings/models.py - 가상 피팅 데이터 모델

이 모듈은 가상 피팅 기능에 필요한 데이터베이스 모델을 정의합니다.

Models:
    - UserImage: 사용자 전신 이미지
    - FittingImage: 가상 피팅 결과 이미지

ERD 테이블:
    - user_image
    - fitting_image
"""

from django.conf import settings
from django.db import models


class UserImage(models.Model):
    """
    사용자 전신 이미지 모델
    
    가상 피팅에 사용할 사용자의 전신 이미지를 저장합니다.
    이미지는 업로드 시 자동으로 최적화(리사이즈, 압축)됩니다.
    
    Attributes:
        user: 이미지 소유자 (User FK)
        user_image_url: 저장된 이미지 URL (GCS 또는 로컬)
        created_at: 생성 일시
        updated_at: 수정 일시
        is_deleted: 소프트 삭제 여부
    
    Related:
        - fitting_images: 이 이미지로 생성된 피팅 결과들
    """
    
    # === 관계 필드 ===
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_images',
        db_column='user_id',
        verbose_name='사용자',
    )

    # === 이미지 필드 ===
    user_image_url = models.ImageField(
        upload_to='user-images/%Y/%m/%d/',
        verbose_name='사용자 이미지 URL',
    )

    # === 타임스탬프 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 일자',
    )

    # === 소프트 삭제 ===
    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    class Meta:
        db_table = 'user_image'
        ordering = ['-created_at']
        verbose_name = '사용자 이미지'
        verbose_name_plural = '사용자 이미지 목록'

    def __str__(self):
        return f"UserImage #{self.pk} - {self.user}"


class FittingImage(models.Model):
    """
    가상 피팅 결과 이미지 모델
    
    사용자 이미지와 상품 이미지를 조합하여 The New Black API로
    생성된 가상 피팅 결과를 저장합니다.
    
    Attributes:
        user_image: 원본 사용자 이미지 (UserImage FK)
        product: 피팅 대상 상품 (Product FK)
        fitting_image_status: 피팅 처리 상태
        fitting_image_url: 생성된 피팅 이미지 URL
        created_at: 요청 생성 일시
        updated_at: 최종 업데이트 일시
        is_deleted: 소프트 삭제 여부
    
    Status 상태 흐름:
        PENDING -> RUNNING -> DONE (성공)
                           -> FAILED (실패)
    
    캐싱:
        동일한 (user_image, product) 조합에 대해 DONE 상태의 결과가 있으면
        새로운 API 호출 없이 기존 결과를 재사용합니다.
    """
    
    class Status(models.TextChoices):
        """피팅 처리 상태"""
        PENDING = 'PENDING', '대기 중'   # Celery 태스크 대기 중
        RUNNING = 'RUNNING', '처리 중'   # API 호출 진행 중
        DONE = 'DONE', '완료'            # 성공적으로 완료
        FAILED = 'FAILED', '실패'        # 처리 실패

    # === 관계 필드 ===
    user_image = models.ForeignKey(
        UserImage,
        on_delete=models.CASCADE,
        related_name='fitting_images',
        db_column='user_image_id',
        verbose_name='사용자 이미지',
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='fitting_images',
        db_column='product_id',
        verbose_name='상품',
    )

    # === 피팅 결과 필드 ===
    fitting_image_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='피팅 상태',
    )
    fitting_image_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name='피팅 이미지 URL',
    )

    # === 타임스탬프 ===
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 일자',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 일자',
    )

    # === 소프트 삭제 ===
    is_deleted = models.BooleanField(
        default=False,
        verbose_name='삭제 여부',
    )

    class Meta:
        db_table = 'fitting_image'
        ordering = ['-created_at']
        verbose_name = '가상 피팅 이미지'
        verbose_name_plural = '가상 피팅 이미지 목록'

    def __str__(self):
        return f"FittingImage #{self.pk} - {self.fitting_image_status}"
