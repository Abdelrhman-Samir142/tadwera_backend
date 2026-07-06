from django.db import models, transaction
from rest_framework.pagination import PageNumberPagination

from ..models import Notification, Order, Product, UserProfile
from .chat import ChatService
from .wallet import WalletService


class ProductServiceError(Exception):
    def __init__(self, payload, status_code=400):
        self.payload = payload
        self.status_code = status_code


class ProductService:

    @staticmethod
    def get_user_listings(base_queryset, user):
        return base_queryset.filter(owner=user)

    @staticmethod
    def get_orders_queryset(user):
        return (
            Order.objects
            .filter(models.Q(buyer=user) | models.Q(seller=user))
            .select_related('product', 'buyer', 'seller')
        )

    @staticmethod
    def build_purchase_response(order, product):
        return {
            'order_id': order.id,
            'amount': float(order.amount),
            'product_title': product.title,
        }

    @staticmethod
    def get_visible_products_queryset(base_qs, user, action, query_params):
        queryset = base_qs

        if not user.is_authenticated:
            print(f"[get_visible_products_queryset] User is not authenticated. Action: {action}")
            queryset = queryset.filter(status__in=['active', 'sold'])
        else:
            is_admin = False
            try:
                is_admin = user.is_staff or getattr(user.profile, 'role', '') == 'admin'
            except Exception:
                pass
            print(f"[get_visible_products_queryset] User: {user.username}, Is Admin: {is_admin}, Action: {action}")
            if not is_admin:
                if action == 'list':
                    queryset = queryset.filter(status__in=['active', 'sold'])
                else:
                    queryset = queryset.filter(
                        models.Q(status__in=['active', 'sold']) | models.Q(owner=user)
                    )
                    print(f"[get_visible_products_queryset] Queryset count after filter: {queryset.count()}")

        min_price = query_params.get('min_price')
        max_price = query_params.get('max_price')

        if min_price:
            queryset = queryset.filter(price__gte=min_price)
        if max_price:
            queryset = queryset.filter(price__lte=max_price)

        if action == 'list':
            if query_params.get('auctions_only') == 'true':
                queryset = queryset.filter(is_auction=True, auction__is_active=True)

        return queryset

    @staticmethod
    def increment_view_count(product):
        product.views_count += 1
        product.save(update_fields=['views_count'])

    @staticmethod
    def set_listing_defaults(product, owner):
        product.owner = owner
        product.status = 'pending'

    @staticmethod
    def purchase_product(buyer, product_id):
        with transaction.atomic():
            product = (
                Product.objects
                .select_for_update()
                .select_related('owner')
                .get(id=product_id)
            )

            if product.owner == buyer:
                raise ProductServiceError(
                    {'error': 'لا يمكنك شراء منتجك الخاص'},
                    status_code=400,
                )

            if product.status != 'active':
                raise ProductServiceError(
                    {'error': 'هذا المنتج غير متاح للشراء (مباع أو غير نشط)'},
                    status_code=400,
                )

            if product.is_auction:
                raise ProductServiceError(
                    {'error': 'هذا المنتج مطروح في مزاد، لا يمكن شراؤه مباشرة'},
                    status_code=400,
                )

            price = product.price

            buyer_profile = (
                UserProfile.objects
                .select_for_update()
                .get(user=buyer)
            )

            if buyer_profile.wallet_balance < price:
                raise ProductServiceError(
                    {
                        'error': (
                            f'رصيدك غير كافي لشراء هذا المنتج. '
                            f'رصيدك: {buyer_profile.wallet_balance} جنيه، والسعر: {price} جنيه.'
                        ),
                        'insufficient_balance': True,
                        'current_balance': float(buyer_profile.wallet_balance),
                        'required': float(price),
                    },
                    status_code=400,
                )

            WalletService.transfer_purchase_funds(
                buyer, product.owner, price, product.title
            )

            product.status = 'sold'
            product.save(update_fields=['status'])

            order = Order.objects.create(
                buyer=buyer,
                seller=product.owner,
                product=product,
                amount=price,
            )

        return order, product, price

    @staticmethod
    def send_purchase_chat_message(buyer, product, price):
        try:
            conversation, _ = ChatService.start_or_get_conversation(buyer, product.id)
            ChatService.send_message(
                conversation,
                buyer,
                f'🎉 تم شراء المنتج "{product.title}" بمبلغ {price} جنيه. تواصل مع البائع لإتمام التسليم.',
            )
        except Exception:
            pass

    @staticmethod
    def review_product(product, action, reason='مخالف لشروط النشر'):
        if action == 'approve':
            product.status = 'active'
            product.save()

            Notification.objects.create(
                user=product.owner,
                title='تم الموافقة على إعلانك',
                message=f'تمت المراجعة والموافقة على إعلانك: {product.title}',
                related_product=product,
            )
            return product, 'approved'

        if action == 'reject':
            product.status = 'inactive'
            product.save()

            Notification.objects.create(
                user=product.owner,
                title='تم رفض إعلانك',
                message=f'تم رفض إعلانك ({product.title}). السبب: {reason}',
                related_product=product,
            )
            return product, 'rejected'

        raise ProductServiceError(
            {'error': 'Invalid action. Use approve or reject.'},
            status_code=400,
        )

    @staticmethod
    def delete_product(product):
        title = product.title
        product.delete()
        return title

    @staticmethod
    def get_admin_products_list(request):
        queryset = Product.objects.select_related('owner').prefetch_related('images').order_by('-created_at')

        paginator = PageNumberPagination()
        paginator.page_size = 50
        paginated_queryset = paginator.paginate_queryset(queryset, request)

        data = []
        for p in paginated_queryset:
            images = list(p.images.all())
            primary_image = next((img for img in images if img.is_primary), images[0] if images else None)
            data.append({
                'id': p.id,
                'title': p.title,
                'price': str(p.price),
                'category': p.category,
                'condition': p.condition,
                'status': p.status,
                'is_auction': p.is_auction,
                'owner_name': p.owner.username,
                'primary_image': request.build_absolute_uri(primary_image.image.url) if primary_image and primary_image.image else None,
                'created_at': p.created_at.isoformat(),
            })
        return paginator.get_paginated_response(data)
