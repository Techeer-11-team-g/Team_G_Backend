from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """
    관리자 페이지에서 커스텀 유저 모델을 관리하기 위한 설정입니다.
    기본 UserAdmin을 상속받아 비밀번호 변경 등 기본 기능을 그대로 사용합니다.
    """
    model = User
    
    # 목록 화면에서 보여줄 컬럼들
    list_display = ('username', 'email', 'phone_number', 'is_staff', 'is_active')
    
    # 상세 화면에서 추가로 보여줄 필드 설정 (기본 UserAdmin의 fieldsets에 커스텀 필드 추가)
    fieldsets = UserAdmin.fieldsets + (
        ('추가 정보', {'fields': ('phone_number', 'address', 'birth_date', 'user_image_url', 'payment')}),
    )
