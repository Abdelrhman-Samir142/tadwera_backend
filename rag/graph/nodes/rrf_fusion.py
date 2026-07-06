"""
RRF Fusion Node — Reciprocal Rank Fusion.

Merges Vector Search + SQL Search results using the RRF algorithm:
  RRF_score(d) = Σ 1 / (k + rank(d))

Where k = 60 (standard constant that prevents high-ranked items
from dominating too much).

This scientifically ranks results from both retrieval tracks
into a single unified ranking.
"""

import logging
from rag.graph.state import AgentState

logger = logging.getLogger(__name__)

RRF_K = 60  # Standard RRF constant


def rrf_fusion_node(state: AgentState) -> dict:
    """Merge vector + SQL results using Reciprocal Rank Fusion."""
    vector_results = state.get("vector_results", [])
    sql_results = state.get("sql_results", [])

    logger.info(f"[Node/RRF] Fusing {len(vector_results)} vector + {len(sql_results)} SQL results")

    # Build RRF scores
    rrf_scores: dict[int, float] = {}   # product_id → score
    doc_map: dict[int, dict] = {}       # product_id → best doc data

    # Score vector results (ranked by similarity/rerank_score)
    for rank, doc in enumerate(vector_results, start=1):
        pid = doc.get('product_id') or doc.get('id')
        if pid is None:
            continue
        pid = int(pid)
        rrf_scores[pid] = rrf_scores.get(pid, 0) + (1.0 / (RRF_K + rank))
        if pid not in doc_map:
            doc_map[pid] = doc.copy()

    # Score SQL results (ranked by SQL ORDER or insertion order)
    for rank, doc in enumerate(sql_results, start=1):
        pid = doc.get('id') or doc.get('product_id')
        if pid is None:
            continue
        pid = int(pid)
        rrf_scores[pid] = rrf_scores.get(pid, 0) + (1.0 / (RRF_K + rank))
        # SQL results have seller data (from JOINs) — prefer them
        if pid not in doc_map or doc.get('seller_name'):
            doc_map[pid] = doc.copy()

    # Sort by RRF score descending
    ranked_pids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

    # Build fused results
    fused = []
    for pid in ranked_pids[:8]:  # Keep top 8 for synthesis to filter
        doc = doc_map[pid]
        doc['rrf_score'] = round(rrf_scores[pid], 4)
        doc['id'] = pid
        fused.append(doc)

    logger.info(f"[Node/RRF] Fused → {len(fused)} unique products")

    if not fused:
        return {
            "fused_results": [],
            "next_step": "synthesis",
        }

    return {
        "fused_results": fused,
        "next_step": "synthesis",
    }
