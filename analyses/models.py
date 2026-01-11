from django.db import models
from django.conf import settings


class UploadedImage(models.Model):
    """
    업로드된 이미지 테이블
    API: POST /api/v1/uploaded-images
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_images',
        verbose_name='업로드한 사용자',
    )

    image = models.ImageField(
        upload_to='uploaded-images/%Y/%m/%d/',
        verbose_name='이미지 파일',
    )

    original_filename = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='원본 파일명',
    )

    file_size = models.PositiveIntegerField(
        default=0,
        verbose_name='파일 크기(bytes)',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='업로드 일시',
    )

    class Meta:
        db_table = 'uploaded_image'
        ordering = ['-created_at']

    def __str__(self):
        return f"UploadedImage #{self.pk}"