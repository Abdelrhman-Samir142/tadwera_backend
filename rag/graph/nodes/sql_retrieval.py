"""
Node 3: SQL Retrieval — V2 Single-Shot with JOINs.

Uses extracted entities for precise SQL generation.
Returns products with seller data already JOINed.
"""

import logging
from rag.graph.state import AgentState

logger = logging.getLogger(__name__)


def sql_retrieval_node(state: AgentState) -> dict:
    """Generate SQL from entities → execute → return results with seller data."""
    from rag.sql_generator import sql_search

    query = state["query"]
    entities = state.get("entities", {})

    try:
        results, generated_sql = sql_search(query, entities=entities)
        logger.info(f"[Node/SQL] {len(results)} results | SQL: {generated_sql[:60]}")
    except Exception as e:
        logger.error(f"[Node/SQL] Failed: {e}")
        results = []
        generated_sql = ""

    return {
        "sql_results": results,
        "sql_count": len(results),
        "generated_sql": generated_sql,
    }
