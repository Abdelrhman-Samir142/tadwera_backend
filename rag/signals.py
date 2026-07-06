"""
Auto-embed products on save using Django signals.
When a product is created or updated, its embedding is generated
in a background thread to avoid blocking the request.
Also cleans up embeddings when a product is deleted.
"""

import logging
import threading
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import connection

logger = logging.getLogger(__name__)


def _embed_in_background(product_id):
    """Run embedding in a background thread."""
    try:
        from marketplace.models import Product
        from rag.embeddings import embed_product
        product = Product.objects.get(id=product_id)
        embed_product(product)
    except Exception as e:
        logger.error(f"[RAG/Signal] Failed to embed product #{product_id}: {e}")
    finally:
        connection.close()


@receiver(post_save, sender='marketplace.Product')
def auto_embed_product(sender, instance, created, **kwargs):
    """
    Whenever a Product is saved (created or updated), queue an embedding generation.
    Runs in a daemon thread so it doesn't block the HTTP response.
    """
    # Only embed active products
    if instance.status != 'active':
        # If product was deactivated/sold, remove its embedding
        try:
            from rag.models import ProductEmbedding
            ProductEmbedding.objects.filter(product_id=instance.id).delete()
            logger.info(f"[RAG/Signal] Removed embedding for inactive product #{instance.id}")
        except Exception:
            pass
        return

    threading.Thread(
        target=_embed_in_background,
        args=(instance.id,),
        daemon=True,
    ).start()


@receiver(post_delete, sender='marketplace.Product')
def cleanup_embedding_on_delete(sender, instance, **kwargs):
    """
    When a Product is deleted, remove its embedding from the database.
    """
    try:
        from rag.models import ProductEmbedding
        deleted_count, _ = ProductEmbedding.objects.filter(product_id=instance.id).delete()
        if deleted_count:
            logger.info(f"[RAG/Signal] Cleaned up embedding for deleted product #{instance.id}")
    except Exception as e:
        logger.error(f"[RAG/Signal] Failed to clean up embedding for product #{instance.id}: {e}")

def _visual_embed_in_background(product_id, image_path):
    """Run visual embedding in a background thread."""
    try:
        import os
        from django.conf import settings
        from marketplace.models import Product, ProductVisualEmbedding
        from ai.clip_service import get_image_embedding
        
        # Determine full path or URL
        image_bytes = None
        if hasattr(image_path, 'url') and image_path.url.startswith('http'):
            # Cloudinary or other remote storage
            import requests
            response = requests.get(image_path.url)
            image_bytes = response.content
        elif hasattr(image_path, 'path'):
            full_path = image_path.path
            if os.path.exists(full_path):
                with open(full_path, "rb") as f:
                    image_bytes = f.read()
        elif isinstance(image_path, str) and image_path.startswith('http'):
            import requests
            response = requests.get(image_path)
            image_bytes = response.content
        else:
            full_path = os.path.join(settings.MEDIA_ROOT, str(image_path))
            if os.path.exists(full_path):
                with open(full_path, "rb") as f:
                    image_bytes = f.read()
        
        if not image_bytes:
            logger.error(f"[Visual/Signal] Could not load image for product #{product_id}")
            return
        
        vector = get_image_embedding(image_bytes)
        
        if vector:
            product = Product.objects.get(id=product_id)
            # Use update_or_create to handle both new and updated images
            ProductVisualEmbedding.objects.update_or_create(
                product=product,
                defaults={
                    'embedding': vector,
                    'image_url': str(image_path)
                }
            )
            logger.info(f"[Visual/Signal] Saved visual embedding for product #{product_id}")
    except Exception as e:
        logger.error(f"[Visual/Signal] Failed to visual embed product #{product_id}: {e}")
    finally:
        connection.close()


@receiver(post_save, sender='marketplace.ProductImage')
def auto_visual_embed_product(sender, instance, created, **kwargs):
    """
    Whenever a ProductImage is saved and it is the primary image, queue a visual embedding generation.
    """
    if getattr(instance, 'is_primary', False) or created:
        threading.Thread(
            target=_visual_embed_in_background,
            args=(instance.product_id, instance.image),
            daemon=True,
        ).start()

@receiver(post_delete, sender='marketplace.ProductImage')
def cleanup_visual_embedding_on_delete(sender, instance, **kwargs):
    """
    If a primary image is deleted, we might want to delete the embedding
    or wait for a new primary image. For simplicity, delete it.
    """
    if getattr(instance, 'is_primary', False):
        try:
            from marketplace.models import ProductVisualEmbedding
            ProductVisualEmbedding.objects.filter(product_id=instance.product_id).delete()
        except Exception:
            pass
