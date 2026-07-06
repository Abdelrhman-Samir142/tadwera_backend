from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from ..models import Auction, Bid, Product, UserProfile


class StatsService:

    @staticmethod
    def get_landing_page_stats():
        total_users = User.objects.count()
        products_sold = Product.objects.filter(status='sold').count()
        active_auctions = Auction.objects.filter(is_active=True).count()

        # Calculate active governorates/cities from profiles and products
        user_locations = UserProfile.objects.values_list('city', flat=True).distinct()
        product_locations = Product.objects.values_list('location', flat=True).distinct()

        # Combine and convert to set to get unique locations (case insensitive roughly)
        locations = set([loc.lower().strip() for loc in user_locations if loc])
        locations.update([loc.lower().strip() for loc in product_locations if loc])

        active_governorates = len(locations)

        # Calculate real weekly activity (last 7 days)
        today = timezone.now().date()
        weekly_activity = []

        for i in range(6, -1, -1):
            target_date = today - timedelta(days=i)

            # Products created on this day
            products_created = Product.objects.filter(created_at__date=target_date).count()
            # Products sold on this day (using updated_at as proxy for when status changed)
            products_sold_today = Product.objects.filter(status='sold', updated_at__date=target_date).count()
            # Bids placed on this day
            bids_placed = Bid.objects.filter(created_at__date=target_date).count()

            # Activity score
            daily_activity = products_created + products_sold_today + bids_placed

            # Add 1 as base so chart isn't completely flat
            weekly_activity.append(daily_activity + 1)

        # Calculate category distribution of sold products
        category_choices = dict(Product.CATEGORY_CHOICES)
        raw_stats = Product.objects.filter(status='sold') \
            .values('category') \
            .annotate(count=models.Count('id')) \
            .order_by('-count')[:5]

        category_distribution = []
        for item in raw_stats:
            category_distribution.append({
                'name': category_choices.get(item['category'], item['category']),
                'count': item['count']
            })

        return {
            'total_users': total_users,
            'products_sold': products_sold,
            'active_auctions': active_auctions,
            'active_governorates': active_governorates,
            'pending_products': Product.objects.filter(status='pending').count(),
            'weekly_activity': weekly_activity,
            'category_distribution': category_distribution,
        }
