from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    사용자 테이블
    ERD: user
    Django 기본 User 모델을 확장하여 사용
    """
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name='전화번호',
    )

    address = models.TextField(
        blank=True,
        null=True,
        verbose_name='주소',
    )

    birth_date = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='생년월일',
    )

    user_image_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name='프로필 이미지 URL',
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
        db_table = 'user'
        verbose_name = '사용자'
        verbose_name_plural = '사용자 목록'

    def __str__(self):
        return f"{self.username} ({self.email})"
