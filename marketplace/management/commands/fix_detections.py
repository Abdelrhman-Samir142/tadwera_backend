import logging
from django.core.management.base import BaseCommand
from marketplace.models import Product
from ai.classifier import classify_image

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Backfills detected_item for active products with empty detection data.'

    def handle(self, *args, **options):
        # We look for active products (or auctions) that are missing a detected_item
        products = Product.objects.filter(detected_item='').select_related('auction').prefetch_related('images')
        
        count = products.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("All products already have detection data."))
            return

        self.stdout.write(self.style.NOTICE(f"Found {count} products missing detection data. Starting classification..."))

        success_count = 0
        for product in products:
            try:
                first_image = product.images.filter(is_primary=True).first()
                if not first_image:
                    first_image = product.images.first()
                
                if first_image and first_image.image:
                    image_path = first_image.image.path
                    self.stdout.write(f"Classifying product ID: {product.id}...")
                    
                    result = classify_image(image_path)
                    detected_item = result.get('detected_class')
                    
                    if detected_item:
                        product.detected_item = detected_item
                        product.save(update_fields=['detected_item'])
                        success_count += 1
                        self.stdout.write(self.style.SUCCESS(f"  - Detected: {detected_item}"))
                    else:
                        self.stdout.write(self.style.WARNING(f"  - No item detected for ID: {product.id}"))
                else:
                    self.stdout.write(self.style.WARNING(f"  - No images for ID: {product.id}"))
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  - Error classifying ID {product.id}: {str(e)}"))

        self.stdout.write(self.style.SUCCESS(f"Done! Successfully classified {success_count} products."))
