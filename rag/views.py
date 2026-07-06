"""
RAG API Views.
Made graceful: returns a clean error if RAG dependencies are missing.

Chat Session API:
  GET  /rag/sessions/           — list user's sessions
  POST /rag/sessions/           — create a new session
  GET  /rag/sessions/{id}/      — get session with messages
  DELETE /rag/sessions/{id}/    — delete session
  POST /rag/sessions/{id}/send/ — send a message and get AI response
"""

import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)

# Lazy import — RAG engine requires openai, google-generativeai, etc.
_rag_available = True
try:
    from rag.hybrid_engine import rag_query
except ImportError:
    _rag_available = False
    logger.warning("[RAG] Dependencies not installed — RAG search disabled")


@api_view(['POST'])
@permission_classes([AllowAny])
def rag_query_view(request):
    """
    POST /api/rag/query/

    Body: { "query": "عايز غسالة رخيصة في القاهرة", "history": [] }

    Returns:
    {
        "answer": {
            "summary": "لقيتلك 3 غسالات حلوين...",
            "items": [12, 34, 56],
            "suggested_action": "view_listing"
        },
        "meta": {
            "latency_ms": 1200,
            "sql_results": 5,
            "vector_results": 10,
            "merged_results": 8,
            "intent": "search_full",
            "tokens_saved": "0",
            "cache_hit": false
        }
    }
    """
    if not _rag_available:
        return Response(
            {"error": "RAG search غير متاح حالياً (مطلوب تثبيت openai + google-generativeai)"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    query = request.data.get('query', '').strip()
    history = request.data.get('history', [])  # Optional: last 3 messages

    if not query:
        return Response(
            {"error": "الرجاء إدخال سؤال أو كلمة بحث."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if len(query) > 500:
        return Response(
            {"error": "السؤال طويل أوي. حاول تختصر شوية."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        result = rag_query(query, user=request.user, history=history)
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"[RAG/View] Unexpected error: {e}")
        return Response(
            {"error": "حصلت مشكلة في السيرفر. جرب تاني."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def rag_cache_stats_view(request):
    """
    GET /api/rag/cache-stats/

    Returns cache statistics including hit rate and estimated tokens saved.
    Admin-only endpoint.
    """
    from rag.response_cache import get_cache

    cache = get_cache()
    stats = cache.stats()
    return Response(stats, status=status.HTTP_200_OK)


# ── Chat Session Views ───────────────────────────────────────────


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def chat_sessions_view(request):
    """
    GET  /api/rag/sessions/ — list user's chat sessions (latest first)
    POST /api/rag/sessions/ — create a new session
    """
    from rag.models import ChatSession

    if request.method == 'GET':
        sessions = ChatSession.objects.filter(user=request.user).values(
            'id', 'title', 'created_at', 'updated_at'
        )
        return Response(list(sessions))

    # POST: create a new session
    title = request.data.get('title', 'محادثة جديدة')[:200]
    session = ChatSession.objects.create(user=request.user, title=title)
    return Response({
        'id': session.id,
        'title': session.title,
        'created_at': session.created_at,
        'updated_at': session.updated_at,
        'messages': [],
    }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def chat_session_detail_view(request, session_id):
    """
    GET    /api/rag/sessions/{id}/ — get session with all messages
    DELETE /api/rag/sessions/{id}/ — delete session + messages
    """
    from rag.models import ChatSession

    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'DELETE':
        session.delete()
        return Response({'status': 'deleted'}, status=status.HTTP_204_NO_CONTENT)

    # GET: return session with messages
    messages = list(session.messages.values(
        'id', 'role', 'content', 'products_data', 'meta', 'created_at'
    ))
    return Response({
        'id': session.id,
        'title': session.title,
        'created_at': session.created_at,
        'updated_at': session.updated_at,
        'messages': messages,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_session_send_view(request, session_id):
    """
    POST /api/rag/sessions/{id}/send/
    Body: { "query": "..." }

    Appends user + assistant messages to the session.
    Returns the assistant's response.
    """
    from rag.models import ChatSession, ChatMessage

    if not _rag_available:
        return Response(
            {"error": "RAG search غير متاح حالياً"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

    query = request.data.get('query', '').strip()
    if not query:
        return Response({'error': 'الرجاء إدخال رسالة'}, status=status.HTTP_400_BAD_REQUEST)

    if len(query) > 500:
        return Response({'error': 'الرسالة طويلة أوي'}, status=status.HTTP_400_BAD_REQUEST)

    # Build history from existing session messages
    history = [
        {'role': m.role, 'content': m.content}
        for m in session.messages.all()
    ]

    # Save user message
    ChatMessage.objects.create(
        session=session,
        role='user',
        content=query,
    )

    # Auto-generate session title from first message
    if session.title == 'محادثة جديدة' and not history:
        session.title = query[:100]
        session.save(update_fields=['title'])

    try:
        result = rag_query(query, user=request.user, history=history)
    except Exception as e:
        logger.error(f"[RAG/Session] Query failed: {e}")
        result = {
            'answer': {
                'summary': 'حصلت مشكلة في السيرفر. جرب تاني.',
                'items': [],
                'suggested_action': 'view_listing',
            },
            'products_data': [],
            'meta': {},
        }

    # Normalise answer — may be None if final_response was cleared by guardrail retry
    answer = result.get('answer') or {
        'summary': 'مش لاقي نتيجة مطابقة. جرب تغير كلمة البحث أو دور في فئة تانية 🔍',
        'items': [],
        'suggested_action': 'set_agent',
    }

    # Save assistant message
    assistant_msg = ChatMessage.objects.create(
        session=session,
        role='assistant',
        content=answer.get('summary', ''),
        products_data=result.get('products_data', []),
        meta=result.get('meta', {}),
    )

    # Touch session updated_at
    session.save(update_fields=['updated_at'])

    return Response({
        'message_id': assistant_msg.id,
        'answer': answer,
        'products_data': result.get('products_data', []),
        'meta': result.get('meta', {}),
    }, status=status.HTTP_200_OK)
