from ..models import Product, Wishlist


class WishlistService:

    @staticmethod
    def list_wishlist_products(user, request):
        wishlist_items = Wishlist.objects.filter(user=user).select_related(
            'product', 'product__owner'
        ).prefetch_related('product__images')

        products_data = []
        for item in wishlist_items:
            product = item.product
            primary_image = product.images.filter(is_primary=True).first()
            if not primary_image:
                primary_image = product.images.first()

            products_data.append({
                'id': product.id,
                'title': product.title,
                'price': str(product.price),
                'category': product.category,
                'condition': product.condition,
                'status': product.status,
                'is_auction': product.is_auction,
                'primary_image': request.build_absolute_uri(primary_image.image.url) if primary_image else None,
                'owner_name': product.owner.username,
                'created_at': product.created_at.isoformat(),
                'wishlisted_at': item.created_at.isoformat(),
            })

        return products_data

    @staticmethod
    def toggle_wishlist(user, product_id):
        product = Product.objects.get(id=product_id)

        wishlist_item, created = Wishlist.objects.get_or_create(
            user=user,
            product=product
        )

        if not created:
            wishlist_item.delete()
            return {'status': 'removed', 'is_wishlisted': False}, 200

        return {'status': 'added', 'is_wishlisted': True}, 201

    @staticmethod
    def is_wishlisted(user, product_id):
        return Wishlist.objects.filter(
            user=user,
            product_id=product_id
        ).exists()

    @staticmethod
    def get_wishlisted_product_ids(user):
        return list(Wishlist.objects.filter(user=user).values_list('product_id', flat=True))
