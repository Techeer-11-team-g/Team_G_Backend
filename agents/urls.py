"""
AI 패션 어시스턴트 - URL 라우팅
"""

from django.urls import path
from agents.views import ChatView, ChatStatusView, ChatSessionView

urlpatterns = [
    # 채팅 API
    path('chat', ChatView.as_view(), name='chat'),

    # 상태 확인 API
    path('chat/status', ChatStatusView.as_view(), name='chat_status'),

    # 세션 관리 API
    path('chat/sessions', ChatSessionView.as_view(), name='chat_sessions'),
    path('chat/sessions/<str:session_id>', ChatSessionView.as_view(), name='chat_session_detail'),
]
