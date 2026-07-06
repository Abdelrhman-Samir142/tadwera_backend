"""
RAG Graph — V2 Architecture (5-Node Pipeline).

Flow:
  Router → [instant_response | followup |
            (vector_retrieval + sql_retrieval) parallel]
  → rrf_fusion → synthesis (with guardrails)
  → [END | retry→synthesis]

Optimizations vs V1:
- 11 nodes → 5 nodes
- 3 LLM calls → 1 LLM call (synthesis only)
- Data enrichment eliminated (SQL JOINs)
- RRF Fusion for scientific ranking
- Inline guardrails (no separate LLM call)
"""

import logging
from langgraph.graph import StateGraph, END
from rag.graph.state import AgentState
from rag.graph.config import setup_langsmith

# ── Import V2 nodes ──
from rag.graph.nodes.intent_router import router_node
from rag.graph.nodes.instant_response import instant_response_node
from rag.graph.nodes.followup import followup_node
from rag.graph.nodes.vector_retrieval import vector_retrieval_node
from rag.graph.nodes.sql_retrieval import sql_retrieval_node
from rag.graph.nodes.rrf_fusion import rrf_fusion_node
from rag.graph.nodes.synthesis import synthesis_node

logger = logging.getLogger(__name__)


def build_rag_graph():
    """Build and compile the V2 RAG StateGraph."""

    setup_langsmith()
    graph = StateGraph(AgentState)

    # ═══════════════════════════════════════════════════════
    # 1. Register Nodes (5 core + 2 terminal)
    # ═══════════════════════════════════════════════════════
    graph.add_node("router",            router_node)
    graph.add_node("instant_response",  instant_response_node)
    graph.add_node("followup",          followup_node)
    graph.add_node("vector_retrieval",  vector_retrieval_node)
    graph.add_node("sql_retrieval",     sql_retrieval_node)
    graph.add_node("rrf_fusion",        rrf_fusion_node)
    graph.add_node("synthesis",         synthesis_node)

    # ═══════════════════════════════════════════════════════
    # 2. Entry Point
    # ═══════════════════════════════════════════════════════
    graph.set_entry_point("router")

    # ═══════════════════════════════════════════════════════
    # 3. Router → conditional routing
    # ═══════════════════════════════════════════════════════
    def _route_after_router(state):
        ns = state["next_step"]
        if ns == "instant_response":
            return ["instant_response"]
        elif ns == "followup":
            return ["followup"]
        else:  # "retrieval" → fan-out to both
            return ["vector_retrieval", "sql_retrieval"]

    graph.add_conditional_edges(
        "router",
        _route_after_router,
        ["instant_response", "followup", "vector_retrieval", "sql_retrieval"]
    )

    # ═══════════════════════════════════════════════════════
    # 5. Fan-In: RRF Fusion
    # ═══════════════════════════════════════════════════════
    graph.add_edge("vector_retrieval", "rrf_fusion")
    graph.add_edge("sql_retrieval", "rrf_fusion")

    # ═══════════════════════════════════════════════════════
    # 6. Fusion → Synthesis
    # ═══════════════════════════════════════════════════════
    graph.add_edge("rrf_fusion", "synthesis")

    # ═══════════════════════════════════════════════════════
    # 7. Self-Correction Loop
    # ═══════════════════════════════════════════════════════
    graph.add_conditional_edges(
        "synthesis",
        lambda state: state["next_step"],
        {"end": END, "retry": "synthesis"}
    )

    # ═══════════════════════════════════════════════════════
    # 8. Terminal Edges
    # ═══════════════════════════════════════════════════════
    graph.add_edge("instant_response", END)
    graph.add_edge("followup", END)

    # ═══════════════════════════════════════════════════════
    # 9. Compile
    # ═══════════════════════════════════════════════════════
    compiled = graph.compile()
    logger.info("[LangGraph] V2 RAG graph compiled ✓ (5 nodes)")
    return compiled


# ── Singleton ──
_rag_agent = None


def get_rag_agent():
    """Get (or build) the compiled RAG agent."""
    global _rag_agent
    if _rag_agent is None:
        _rag_agent = build_rag_graph()
    return _rag_agent
