from django.db import models


class SizeGroup(models.Model):
    """
    사이즈 그룹 테이블
    ERD: size_group
    사이즈 체계 그룹 (예: 의류 사이즈, 신발 사이즈 등)
    """
    category = models.CharField(
        max_length=100,
        verbose_name='카테고리',
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
        db_table = 'size_group'
        verbose_name = '사이즈 그룹'
        verbose_name_plural = '사이즈 그룹 목록'

    def __str__(self):
        return self.category


class SizeCode(models.Model):
    """
    사이즈 코드 테이블
    ERD: size_code
    개별 사이즈 정보 (S, M, L, 260, 270 등)
    """
    size_group = models.ForeignKey(
        SizeGroup,
        on_delete=models.CASCADE,
        related_name='size_codes',
        db_column='size_group_id',
        verbose_name='사이즈 그룹',
    )

    size_value = models.CharField(
        max_length=50,
        verbose_name='사이즈 값',
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
        db_table = 'size_code'
        verbose_name = '사이즈 코드'
        verbose_name_plural = '사이즈 코드 목록'

    def __str__(self):
        return f"{self.size_group.category} - {self.size_value}"


class Product(models.Model):
    """
    상품 테이블
    ERD: product
    상품 기본 정보
    """
    brand_name = models.CharField(
        max_length=200,
        verbose_name='브랜드명',
    )

    product_name = models.CharField(
        max_length=500,
        verbose_name='상품명',
    )

    product_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name='상품 URL',
    )

    selling_price = models.PositiveIntegerField(
        default=0,
        verbose_name='판매가',
    )

    product_image_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name='상품 이미지 URL',
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
        db_table = 'product'
        verbose_name = '상품'
        verbose_name_plural = '상품 목록'

    def __str__(self):
        return f"[{self.brand_name}] {self.product_name}" 