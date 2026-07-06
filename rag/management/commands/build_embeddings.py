"""
Management command to build embeddings for all existing products.

Usage:
    python manage.py build_embeddings          # embed all active products
    python manage.py build_embeddings --all    # embed ALL products regardless of status
    python manage.py build_embeddings --batch 50  # custom batch size
"""

import time
import logging
from django.core.management.base import BaseCommand
from marketplace.models import Product
from rag.embeddings import embed_product

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Generate vector embeddings for all products (for RAG search).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Embed all products, not just active ones',
        )
        parser.add_argument(
            '--batch',
            type=int,
            default=20,
            help='Batch size (default: 20). Pause between batches to respect rate limits.',
        )

    def handle(self, *args, **options):
        embed_all = options['all']
        batch_size = options['batch']

        queryset = Product.objects.all() if embed_all else Product.objects.filter(status='active')
        total = queryset.count()

        self.stdout.write(self.style.SUCCESS(
            f"[RAG] Building embeddings for {total} products (batch={batch_size})..."
        ))

        success = 0
        errors = 0

        for i, product in enumerate(queryset.iterator(), 1):
            try:
                embed_product(product)
                success += 1
                self.stdout.write(f"  [{i}/{total}] OK #{product.id}: {product.title[:40]}")
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(
                    f"  [{i}/{total}] FAIL #{product.id}: {e}"
                ))

            # Rate limit: pause every batch_size items
            if i % batch_size == 0 and i < total:
                self.stdout.write(f"  ... Pausing 2s (rate limit)...")
                time.sleep(2)

        self.stdout.write(self.style.SUCCESS(
            f"\n[RAG] Done! {success} embedded, {errors} failed out of {total} total."
        ))
