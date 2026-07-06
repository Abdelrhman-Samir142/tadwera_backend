from marketplace.visual_search import search_by_image
from rag.models import ProductEmbedding


class VisualSearchError(Exception):
    def __init__(self, payload, status_code=503):
        self.payload = payload
        self.status_code = status_code


class VisualSearchService:

    @staticmethod
    def search_similar_products(image_file, request, top_k=12):
        embedding_count = ProductEmbedding.objects.count()
        if embedding_count == 0:
            raise VisualSearchError(
                {'error': 'لا توجد بيانات منتجات مفهرسة بعد.'},
                status_code=503,
            )

        image_bytes = image_file.read()

        results, ai_description = search_by_image(image_bytes, top_k=top_k)

        products_data = []
        for product, score in results:
            primary_image = product.images.filter(is_primary=True).first()
            if not primary_image:
                primary_image = product.images.first()

            image_url = None
            if primary_image and primary_image.image:
                try:
                    image_url = request.build_absolute_uri(primary_image.image.url)
                except Exception:
                    image_url = primary_image.image.url if primary_image.image else None

            seller_data = None
            try:
                profile = product.owner.profile
                seller_data = {
                    'id': product.owner.id,
                    'name': f"{product.owner.first_name} {product.owner.last_name}".strip() or product.owner.username,
                    'avatar_url': request.build_absolute_uri(profile.avatar.url) if profile.avatar else None,
                    'is_verified': profile.is_verified,
                }
            except Exception:
                seller_data = {
                    'id': product.owner.id,
                    'name': product.owner.username,
                    'avatar_url': None,
                    'is_verified': False,
                }

            products_data.append({
                'id': product.id,
                'title': product.title,
                'price': str(product.price),
                'category': product.category,
                'condition': product.condition,
                'status': product.status,
                'location': product.location,
                'is_auction': product.is_auction,
                'primary_image': image_url,
                'owner_name': product.owner.username,
                'owner_id': product.owner.id,
                'seller': seller_data,
                'similarity_score': round(score, 4),
                'views_count': product.views_count,
                'created_at': product.created_at.isoformat(),
            })

        return {
            'results': products_data,
            'total': len(products_data),
            'ai_description': ai_description,
            'total_indexed': embedding_count,
        }
