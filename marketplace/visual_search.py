"""
Visual Search Service using CLIP Embeddings + pgvector.

Flow:
1. Accept an image (file upload)
2. Use HF CLIP (via clip_service.py) to extract a 512-dim embedding
3. Use pgvector's CosineDistance to find similar products in the database
4. Return the most similar products
"""

import logging
from pgvector.django import CosineDistance
from ai.clip_service import get_image_embedding

logger = logging.getLogger(__name__)

def search_by_image(image_bytes: bytes, top_k: int = 12):
    """
    Full visual search pipeline using pgvector and CLIP.
    """
    from marketplace.models import ProductVisualEmbedding

    # Step 1: Embed the query image
    try:
        query_vector = get_image_embedding(image_bytes)
        if not query_vector:
            raise ValueError("Failed to generate embedding for the uploaded image")
    except Exception as e:
        logger.error(f"[VisualSearch] Embedding failed: {e}")
        raise Exception("فشل تحليل الصورة. يرجى المحاولة مرة أخرى.")

    logger.info(f"[VisualSearch] Query embedding generated: {len(query_vector)} dims")

    # Step 2: Search in the database using pgvector's CosineDistance
    # pgvector handles the similarity calculation inside PostgreSQL (very fast!)
    similar_embeddings = ProductVisualEmbedding.objects.select_related(
        'product', 'product__owner', 'product__owner__profile'
    ).prefetch_related('product__images').annotate(
        distance=CosineDistance('embedding', query_vector)
    ).order_by('distance')[:top_k]

    scored = []
    for emb in similar_embeddings:
        # CosineDistance returns a distance where 0 is identical and 2 is opposite
        # We can convert distance to a similarity score between 0 and 1
        similarity_score = 1 - (emb.distance if emb.distance is not None else 1)
        # We only include results that have some baseline similarity
        if similarity_score > 0.1:
            scored.append((emb.product, similarity_score))

    description = "بحث بالصورة باستخدام مطابقة الذكاء الاصطناعي (CLIP)"
    return scored, description
