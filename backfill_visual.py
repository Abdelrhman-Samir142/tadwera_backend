import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'refurbai_backend.settings')
django.setup()

from marketplace.models import Product, ProductImage, ProductVisualEmbedding
from ai.clip_service import get_image_embedding
from rag.signals import _visual_embed_in_background
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def backfill_visual_embeddings():
    products = Product.objects.all()
    count = 0
    for product in products:
        # Get primary image or first image
        image = product.images.filter(is_primary=True).first()
        if not image:
            image = product.images.first()
            
        if image:
            # Check if embedding already exists
            if not hasattr(product, 'visual_embedding'):
                logger.info(f"Generating visual embedding for Product #{product.id}: {product.title}")
                try:
                    # Run synchronously for the script
                    _visual_embed_in_background(product.id, image.image)
                    count += 1
                except Exception as e:
                    logger.error(f"Failed for product {product.id}: {e}")
                    
    logger.info(f"Successfully backfilled {count} visual embeddings.")

if __name__ == '__main__':
    backfill_visual_embeddings()
