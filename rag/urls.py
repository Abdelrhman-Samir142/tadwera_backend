from django.urls import path
from .views import (
    rag_query_view,
    rag_cache_stats_view,
    chat_sessions_view,
    chat_session_detail_view,
    chat_session_send_view,
)

urlpatterns = [
    # Legacy stateless endpoint
    path('query/', rag_query_view, name='rag-query'),
    path('cache-stats/', rag_cache_stats_view, name='rag-cache-stats'),

    # Chat session endpoints
    path('sessions/', chat_sessions_view, name='chat-sessions'),
    path('sessions/<int:session_id>/', chat_session_detail_view, name='chat-session-detail'),
    path('sessions/<int:session_id>/send/', chat_session_send_view, name='chat-session-send'),
]
