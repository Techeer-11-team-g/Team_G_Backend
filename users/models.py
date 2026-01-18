"""
users/models.py - 사용자 데이터 모델

이 모듈은 사용자 인증 및 프로필 관련 데이터베이스 모델을 정의합니다.
Django의 AbstractUser를 확장하여 추가 필드를 제공합니다.

Models:
    - User: 사용자 계정 정보

ERD 테이블:
    - user
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    사용자 모델
    
    Django 기본 AbstractUser를 확장하여 프로필 정보를 추가합니다.
    
    Attributes:
        username: 사용자 아이디 (AbstractUser 상속)
        email: 이메일 주소 (AbstractUser 상속)
        password: 비밀번호 (AbstractUser 상속, 해시 저장)
        phone_number: 전화번호
        payment: 결제 수단 정보
        address: 배송 주소
        birth_date: 생년월일
        user_image_url: 프로필 이미지 URL
        created_at: 가입 일시
        updated_at: 정보 수정 일시
        is_deleted: 소프트 삭제 여부
    
    Note:
        - AbstractUser의 first_name, last_name은 사용하지 않음
        - 소프트 삭제 방식 사용 (is_deleted)
    """
    
    # === 프로필 필드 ===
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name='전화번호',
    )
    payment = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='결제 수단',
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
        db_table = 'user'
        verbose_name = '사용자'
        verbose_name_plural = '사용자 목록'

    def __str__(self):
        return f"{self.username} ({self.email})"
