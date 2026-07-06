"""
Management command to generate CLIP visual embeddings for all existing products.
This runs in the background and calls the HF API for each product image.

Usage:
    python manage.py generate_visual_embeddings
    python manage.py generate_visual_embeddings --force   # Re-generate all
"""

import sys
import io
import time
from django.core.management.base import BaseCommand
from marketplace.models import Product, ProductVisualEmbedding
from marketplace.visual_search import generate_product_embedding


class Command(BaseCommand):
    help = 'Generate CLIP visual embeddings for all product images via HF API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-generate embeddings even if they already exist',
        )

    def handle(self, *args, **options):
        # Fix Windows encoding for Arabic text
        if sys.platform == 'win32':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

        force = options['force']

        products = Product.objects.filter(
            status='active'
        ).prefetch_related('images')

        total = products.count()
        print(f"\n{'='*60}")
        print(f"  Visual Search: Generating CLIP embeddings")
        print(f"  Total active products: {total}")
        print(f"  Force re-generate: {force}")
        print(f"{'='*60}\n")

        success = 0
        skipped = 0
        failed = 0

        for i, product in enumerate(products, 1):
            # Skip if already has embedding (unless --force)
            if not force and ProductVisualEmbedding.objects.filter(product=product).exists():
                skipped += 1
                print(f"  [{i}/{total}] SKIP  #{product.id} - already embedded")
                continue

            # Skip if no images
            if not product.images.exists():
                skipped += 1
                print(f"  [{i}/{total}] SKIP  #{product.id} - no images")
                continue

            # Use product ID only to avoid encoding issues
            print(f"  [{i}/{total}] Processing product #{product.id}...", end='', flush=True)

            try:
                result = generate_product_embedding(product)
                if result:
                    success += 1
                    print(' OK')
                else:
                    skipped += 1
                    print(' SKIPPED (no valid image)')
            except Exception as e:
                failed += 1
                print(f' FAILED: {e}')

            # Rate limit: HF free tier has limits, add a small delay
            time.sleep(1)

        print(f"\n{'='*60}")
        print(f"  DONE!")
        print(f"  Success: {success}")
        print(f"  Skipped: {skipped}")
        if failed:
            print(f"  Failed:  {failed}")
        print(f"{'='*60}\n")
