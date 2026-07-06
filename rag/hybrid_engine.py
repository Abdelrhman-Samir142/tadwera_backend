"""
Hybrid RAG Engine — V2 (LangGraph wrapper).

Thin wrapper that delegates to the V2 LangGraph agent.
API surface stays identical — no frontend changes needed.
"""

import time
import logging

logger = logging.getLogger(__name__)


def rag_query(query: str, user=None, history: list = None) -> dict:
    """
    Full RAG pipeline — delegates to the V2 LangGraph agent.

    Returns:
    {
        "answer": {"summary": ..., "items": [...], "suggested_action": ...},
        "products_data": [...],
        "meta": {"latency_ms": ..., "sql_results": ..., ...}
    }
    """
    from rag.models import RAGQueryLog
    from rag.response_cache import get_cache
    from rag.graph.rag_graph import get_rag_agent

    start = time.time()
    error_msg = ""
    cache = get_cache()
    uid = str(user.id) if user and hasattr(user, 'id') and user.is_authenticated else "anon"

    # ── Cache Check ──
    cached = cache.get(query, user_id=uid)
    if cached:
        latency_ms = int((time.time() - start) * 1000)
        result = cached.copy()
        result["meta"] = {**result.get("meta", {}), "latency_ms": latency_ms, "cache_hit": True}
        _log(user, query, result, latency_ms, "")
        return result

    # ── Run V2 LangGraph ──
    try:
        agent = get_rag_agent()

        initial_state = {
            "query": query,
            "messages": history or [],
            "retry_count": 0,
            "entities": {},
            "vector_results": [],
            "sql_results": [],
            "fused_results": [],
            "products_data": [],
            "vector_count": 0,
            "sql_count": 0,
            "generated_sql": "",
            "metadata": {},
        }

        final_state = agent.invoke(initial_state)

        answer = final_state.get("final_response", {
            "summary": "حصلت مشكلة تقنية. جرب تاني بعد شوية.",
            "items": [],
            "suggested_action": "view_listing",
        })
        products_data = final_state.get("products_data", [])
        sql_count = final_state.get("sql_count", 0)
        vector_count = final_state.get("vector_count", 0)
        generated_sql = final_state.get("generated_sql", "")
        fused_count = len(final_state.get("fused_results", []))
        intent = final_state.get("intent", "unknown")

    except Exception as e:
        logger.error(f"[RAG] LangGraph pipeline error: {e}")
        error_msg = str(e)
        answer = {
            "summary": "حصلت مشكلة تقنية. جرب تاني بعد شوية.",
            "items": [],
            "suggested_action": "view_listing",
        }
        products_data = []
        sql_count = vector_count = fused_count = 0
        generated_sql = ""
        intent = "error"

    latency_ms = int((time.time() - start) * 1000)

    result = {
        "answer": answer,
        "products_data": products_data,
        "meta": {
            "latency_ms": latency_ms,
            "sql_results": sql_count,
            "vector_results": vector_count,
            "fused_results": fused_count,
            "intent": intent,
            "cache_hit": False,
        }
    }

    # ── Cache ──
    if not error_msg:
        cache.set(query, result, user_id=uid)

    # ── Log ──
    _log(user, query, result, latency_ms, error_msg, generated_sql)

    return result


def _log(user, query, result, latency_ms, error, sql=""):
    """Log query to database."""
    from rag.models import RAGQueryLog
    try:
        meta = result.get("meta", {})
        RAGQueryLog.objects.create(
            user=user if user and user.is_authenticated else None,
            query_text=query,
            generated_sql=sql or "[N/A]",
            sql_results_count=meta.get("sql_results", 0),
            vector_results_count=meta.get("vector_results", 0),
            merged_results_count=meta.get("fused_results", 0),
            final_answer=result.get("answer", {}).get("summary", ""),
            latency_ms=latency_ms,
            error=error,
        )
    except Exception as e:
        logger.error(f"[RAG] Logging failed: {e}")
