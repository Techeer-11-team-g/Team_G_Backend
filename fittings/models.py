from django.db import models
from django.conf import settings


class UserImage(models.Model):
    """
    사용자 이미지 테이블
    ERD: user_image
    가상 피팅에 사용할 사용자 전신 이미지
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_images',
        db_column='user_id',
        verbose_name='사용자',
    )

    user_image_url = models.ImageField(
        upload_to='user-images/%Y/%m/%d/',
        verbose_name='사용자 이미지 URL',
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
        db_table = 'user_image'
        ordering = ['-created_at']
        verbose_name = '사용자 이미지'
        verbose_name_plural = '사용자 이미지 목록'

    def __str__(self):
        return f"UserImage #{self.pk} - {self.user}"


class FittingImage(models.Model):
    """
    가상 피팅 이미지 테이블
    ERD: fitting_image
    The New Black API를 통해 생성된 가상 피팅 결과 이미지
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', '대기 중'
        RUNNING = 'RUNNING', '처리 중'
        DONE = 'DONE', '완료'
        FAILED = 'FAILED', '실패'

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
        db_table = 'fitting_image'
        ordering = ['-created_at']
        verbose_name = '가상 피팅 이미지'
        verbose_name_plural = '가상 피팅 이미지 목록'

    def __str__(self):
        return f"FittingImage #{self.pk} - {self.fitting_image_status}"
