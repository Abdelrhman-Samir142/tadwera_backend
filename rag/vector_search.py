"""
Vector Search — V2 with Lightweight Re-ranking.

1. Cosine similarity search (Gemini embeddings)
2. Heuristic re-ranking: boost scores based on keyword overlap,
   price relevance, and location match
3. Returns top-K results with enriched scores
"""

import logging
import numpy as np
from rag.embeddings import generate_query_embedding
from rag.intent_router import normalize_arabic

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 10   # Fetch more candidates for re-ranking
FINAL_TOP_K = 4      # Return top 4 after re-ranking
MIN_SIMILARITY = 0.15


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _rerank(results: list[dict], query: str, entities: dict) -> list[dict]:
    """
    Lightweight heuristic re-ranking. Zero external dependencies.
    
    Boosts:
    - Keyword overlap with query (+0.15 per keyword hit)
    - Price within range (+0.1)
    - Location match (+0.1)
    - Category match (+0.1)
    """
    if not results:
        return results

    query_words = set(normalize_arabic(query).split())
    product_term = normalize_arabic(entities.get("product", query))
    product_words = set(product_term.split())
    price_min = entities.get("price_min")
    price_max = entities.get("price_max")
    location = entities.get("location")
    category = entities.get("category")

    for item in results:
        boost = 0.0
        title_norm = normalize_arabic(item.get('title', ''))

        # Keyword overlap boost
        title_words = set(title_norm.split())
        overlap = product_words & title_words
        boost += len(overlap) * 0.15

        # Exact product term in title
        if product_term in title_norm:
            boost += 0.2

        # Price relevance
        price = item.get('price', 0)
        if price and price_max and price <= price_max:
            boost += 0.1
        if price and price_min and price >= price_min:
            boost += 0.05

        # Location match
        if location and location in (item.get('location', '') or ''):
            boost += 0.1

        # Category match
        if category and item.get('category') == category:
            boost += 0.1

        item['rerank_score'] = item.get('similarity', 0) + boost

    # Sort by re-ranked score
    results.sort(key=lambda x: x.get('rerank_score', 0), reverse=True)
    return results[:FINAL_TOP_K]


def vector_search(query_text: str, entities: dict = None, top_k: int = FINAL_TOP_K) -> list[dict]:
    """
    Embed query → cosine search → heuristic re-rank → top K.
    
    Args:
        query_text: Raw user query
        entities: Extracted {product, price_min, price_max, location, category}
        top_k: Number of results to return
    """
    from rag.models import ProductEmbedding

    if entities is None:
        entities = {"product": query_text}

    try:
        query_vector = generate_query_embedding(query_text)
    except Exception as e:
        logger.error(f"[Vector] Failed to embed query: {e}")
        return []

    query_vec = np.array(query_vector, dtype=np.float32)

    # Load all embeddings for active products
    embeddings = ProductEmbedding.objects.filter(
        product__status='active'
    ).select_related('product').all()

    if not embeddings:
        logger.info("[Vector] No embeddings in database.")
        return []

    # Cosine similarity scoring
    scored = []
    for pe in embeddings:
        try:
            product_vec = np.array(pe.embedding, dtype=np.float32)
            sim = _cosine_similarity(query_vec, product_vec)
            if sim >= MIN_SIMILARITY:
                scored.append((sim, pe))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = scored[:DEFAULT_TOP_K]  # Over-fetch for re-ranking

    # Build result dicts
    results = []
    for similarity, pe in candidates:
        product = pe.product
        results.append({
            'product_id': product.id,
            'title': product.title,
            'description': product.description[:200] if product.description else '',
            'price': float(product.price),
            'category': product.category,
            'condition': product.condition,
            'location': product.location,
            'status': product.status,
            'is_auction': product.is_auction,
            'similarity': round(similarity, 4),
            'source': 'vector',
        })

    # Re-rank with heuristics
    results = _rerank(results, query_text, entities)

    logger.info(f"[Vector] {len(results)} results after re-ranking for: '{query_text[:40]}'")
    return results
