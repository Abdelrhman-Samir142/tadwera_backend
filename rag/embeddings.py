"""
Embedding generation utilities.

Uses Google Gemini's text-embedding-004 model (768 dimensions).
This is FREE and works with the existing GEMINI_API_KEY.

The embedding text is a structured concatenation of product fields
designed to capture maximum semantic meaning for Egyptian marketplace items.
"""

import os
import logging
import google.generativeai as genai

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 768

_configured = False


def _configure():
    global _configured
    if not _configured:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        genai.configure(api_key=api_key)
        _configured = True


def build_embedding_text(product) -> str:
    """
    Build a rich text string from a product for embedding.
    Concatenates title, description, condition, category label, and location.
    """
    from ai.classifier import YOLO_CLASS_LABELS

    detected_label = ""
    if product.detected_item:
        detected_label = YOLO_CLASS_LABELS.get(product.detected_item, product.detected_item)

    condition_map = {
        'new': 'جديد',
        'like-new': 'زي الجديد',
        'good': 'حالة جيدة',
        'fair': 'مقبول',
    }
    condition_ar = condition_map.get(product.condition, product.condition)

    category_map = {
        'scrap_metals': 'خردة ومعادن',
        'electronics': 'إلكترونيات وأجهزة',
        'furniture': 'أثاث وديكور',
        'cars': 'سيارات',
        'real_estate': 'عقارات',
        'books': 'كتب',
        'other': 'أخرى',
    }
    category_ar = category_map.get(product.category, product.category)

    parts = [
        product.title,
        f"| الوصف: {product.description}" if product.description else "",
        f"| الحالة: {condition_ar}",
        f"| الفئة: {category_ar}",
        f"| الصنف: {detected_label}" if detected_label else "",
        f"| الموقع: {product.location}" if product.location else "",
        f"| السعر: {product.price} جنيه",
    ]
    return " ".join(p for p in parts if p)


def generate_embedding(text: str) -> list[float]:
    """
    Call Gemini embedding API and return the vector.
    """
    try:
        _configure()
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=text,
            task_type="retrieval_document",
        )
        return result['embedding']
    except Exception as e:
        logger.error(f"[RAG] Embedding generation failed: {e}")
        raise


def generate_query_embedding(text: str) -> list[float]:
    """
    Generate embedding specifically for queries (uses retrieval_query task type).
    """
    try:
        _configure()
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=text,
            task_type="retrieval_query",
        )
        return result['embedding']
    except Exception as e:
        logger.error(f"[RAG] Query embedding failed: {e}")
        raise


def embed_product(product) -> None:
    """
    Generate and store an embedding for a single product.
    Creates or updates the ProductEmbedding row.
    """
    from rag.models import ProductEmbedding

    text = build_embedding_text(product)
    vector = generate_embedding(text)

    ProductEmbedding.objects.update_or_create(
        product=product,
        defaults={
            'embedding': vector,
            'embedded_text': text,
            'model_name': EMBEDDING_MODEL,
        }
    )
    logger.info(f"[RAG] Embedded product #{product.id}: {product.title[:40]}")
