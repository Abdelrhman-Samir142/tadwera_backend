"""
Node 2: Vector Retrieval — V2 with Re-ranking.

Semantic search using Gemini embeddings + heuristic re-ranking.
"""

import logging
from rag.graph.state import AgentState

logger = logging.getLogger(__name__)


def vector_retrieval_node(state: AgentState) -> dict:
    """Run vector search with re-ranking using extracted entities."""
    from rag.vector_search import vector_search

    query = state["query"]
    entities = state.get("entities", {})

    try:
        results = vector_search(query, entities=entities)
        logger.info(f"[Node/Vector] {len(results)} results after re-ranking")
    except Exception as e:
        logger.error(f"[Node/Vector] Failed: {e}")
        results = []

    return {
        "vector_results": results,
        "vector_count": len(results),
    }
