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

      # ImageField는 DB에 varchar로 URL 경로를 저장함
      uploaded_image_url = models.ImageField(
          upload_to='uploaded-images/%Y/%m/%d/',
          verbose_name='업로드한 이미지 URL',
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
          db_table = 'uploaded_image'
          ordering = ['-created_at']

      def __str__(self):
          return f"UploadedImage #{self.pk}"