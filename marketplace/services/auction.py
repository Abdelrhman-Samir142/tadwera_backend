from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from ..models import Auction, Bid, Notification, UserProfile
from .chat import ChatService
from .wallet import WalletService


class AuctionBidError(Exception):
    def __init__(self, payload, status_code=400):
        self.payload = payload
        self.status_code = status_code


class AuctionService:

    @staticmethod
    def close_expired_auctions():
        """Auto-close expired auctions, refund losers, deduct winner, and notify."""
        expired = Auction.objects.filter(is_active=True, end_time__lte=timezone.now())
        for auction in expired:
            auction.is_active = False
            auction.save(update_fields=['is_active'])
            auction.product.status = 'sold'
            auction.product.save()

            winner = auction.highest_bidder
            all_bids = auction.bids.select_related('bidder', 'bidder__profile').order_by('-amount')

            processed_users = set()

            for bid in all_bids:
                bidder = bid.bidder
                if bidder.id in processed_users:
                    continue
                processed_users.add(bidder.id)

                try:
                    profile = bidder.profile
                except UserProfile.DoesNotExist:
                    continue

                if winner and bidder.id == winner.id:
                    WalletService.record_transaction(
                        user=bidder,
                        amount=bid.amount,
                        transaction_type='bid_deduct',
                        description=f'خصم فوز مزاد: "{auction.product.title}"',
                        balance_after=profile.wallet_balance,
                        related_auction=auction,
                    )
                    try:
                        seller_profile = auction.product.owner.profile
                        seller_profile.wallet_balance += bid.amount
                        seller_profile.total_sales = (seller_profile.total_sales or 0) + 1
                        seller_profile.save(update_fields=['wallet_balance', 'total_sales'])
                        WalletService.record_transaction(
                            user=auction.product.owner,
                            amount=bid.amount,
                            transaction_type='topup',
                            description=f'بيع مزاد: "{auction.product.title}" - الفائز: {bidder.username}',
                            balance_after=seller_profile.wallet_balance,
                            related_auction=auction,
                        )
                    except UserProfile.DoesNotExist:
                        pass
                else:
                    WalletService.refund_bid_amount(
                        user=bidder,
                        amount=bid.amount,
                        auction=auction,
                        description=f'استرداد مزايدة: "{auction.product.title}"',
                        profile=profile,
                    )

            if winner:
                ChatService.send_winner_message(auction)

    @staticmethod
    def get_visible_auctions_queryset(base_qs, user, action, query_params):
        AuctionService.close_expired_auctions()

        queryset = base_qs

        if not user.is_authenticated:
            queryset = queryset.filter(product__status__in=['active', 'sold'])
        else:
            is_admin = False
            try:
                is_admin = user.is_staff or getattr(user.profile, 'role', '') == 'admin'
            except Exception:
                pass

            if not is_admin:
                if action == 'list':
                    queryset = queryset.filter(product__status__in=['active', 'sold'])
                else:
                    queryset = queryset.filter(
                        models.Q(product__status__in=['active', 'sold']) | models.Q(product__owner=user)
                    )

        active_only = query_params.get('active_only', 'false')
        if active_only == 'true':
            queryset = queryset.filter(is_active=True, end_time__gt=timezone.now())

        category = query_params.get('category')
        if category:
            queryset = queryset.filter(product__category=category)

        condition = query_params.get('condition')
        if condition:
            queryset = queryset.filter(product__condition=condition)

        min_price = query_params.get('min_price')
        if min_price:
            queryset = queryset.filter(current_bid__gte=min_price)

        max_price = query_params.get('max_price')
        if max_price:
            queryset = queryset.filter(current_bid__lte=max_price)

        search = query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(product__title__icontains=search) |
                models.Q(product__description__icontains=search) |
                models.Q(product__location__icontains=search)
            )
        return queryset.order_by('-is_active', '-created_at')

    @staticmethod
    def parse_bid_amount(amount_raw):
        try:
            amount = Decimal(str(amount_raw))
        except Exception:
            raise AuctionBidError({'error': 'مبلغ المزايدة غير صالح'}, status_code=400)

        if amount <= 0:
            raise AuctionBidError(
                {'error': 'مبلغ المزايدة يجب أن يكون أكبر من صفر'},
                status_code=400,
            )
        return amount

    @staticmethod
    def ensure_bidder_profile(user):
        return user.profile

    @staticmethod
    def run_agent_counter_bid(auction, user):
        try:
            from ..serializers import agent_counter_bid
            agent_counter_bid(auction, user)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"[Agent] Counter-bid error: {e}")

    @staticmethod
    def build_place_bid_response(bid):
        try:
            from ..serializers import BidSerializer
            return BidSerializer(bid).data
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"[place_bid] BidSerializer crashed: {e}")
            return {
                'id': bid.id,
                'auction': bid.auction_id,
                'bidder': bid.bidder_id,
                'bidder_name': bid.bidder.username,
                'amount': str(bid.amount),
                'created_at': bid.created_at.isoformat() if bid.created_at else None,
            }

    @staticmethod
    def log_place_bid_crash(auction_id, exc):
        import logging
        import traceback
        logging.getLogger(__name__).error(
            f"[place_bid] Atomic block crashed for auction {auction_id}: {exc}\n{traceback.format_exc()}"
        )

    @staticmethod
    def close_auction_on_expiry(auction):
        auction.is_active = False
        auction.save(update_fields=['is_active'])
        auction.product.status = 'sold'
        auction.product.save(update_fields=['status'])
        if auction.highest_bidder:
            ChatService.send_winner_message(auction)

    @staticmethod
    def place_bid(user, auction_id, amount, hold_description=None):
        try:
            with transaction.atomic():
                auction = (
                    Auction.objects
                    .select_for_update()
                    .select_related('product', 'product__owner')
                    .get(id=auction_id)
                )

                if not auction.is_active:
                    raise AuctionBidError({'error': 'المزاد غير نشط'}, status_code=400)

                if auction.product.status != 'active':
                    raise AuctionBidError(
                        {'error': 'المنتج لم تتم الموافقة عليه بعد من قبل الإدارة'},
                        status_code=400,
                    )

                now = timezone.now()
                if auction.end_time < now:
                    AuctionService.close_auction_on_expiry(auction)
                    raise AuctionBidError({'error': 'المزاد انتهى'}, status_code=400)

                if auction.product.owner == user:
                    raise AuctionBidError(
                        {'error': 'لا يمكنك المزايدة على مزادك الخاص'},
                        status_code=400,
                    )

                if amount <= auction.current_bid:
                    raise AuctionBidError(
                        {
                            'error': (
                                f'يجب أن تكون المزايدة أعلى من السعر الحالي '
                                f'({auction.current_bid} جنيه)'
                            )
                        },
                        status_code=400,
                    )

                profile = (
                    UserProfile.objects
                    .select_for_update()
                    .get(user=user)
                )

                previous_bid = (
                    Bid.objects
                    .filter(auction=auction, bidder=user)
                    .order_by('-amount')
                    .first()
                )
                needed = amount - previous_bid.amount if previous_bid else amount

                if profile.wallet_balance < needed:
                    raise AuctionBidError(
                        {
                            'error': (
                                f'رصيدك غير كافي للمزايدة. رصيدك الحالي: '
                                f'{profile.wallet_balance} جنيه، والمطلوب: {needed} جنيه.'
                            ),
                            'insufficient_balance': True,
                            'current_balance': float(profile.wallet_balance),
                            'required': float(needed),
                        },
                        status_code=400,
                    )

                WalletService.hold_bid_amount(
                    profile,
                    auction,
                    amount,
                    previous_bid_amount=previous_bid.amount if previous_bid else None,
                    hold_description=hold_description,
                )

                bid = Bid.objects.create(
                    auction=auction,
                    bidder=user,
                    amount=amount,
                )

                auction.current_bid = amount
                auction.highest_bidder = user
                auction.save(update_fields=['current_bid', 'highest_bidder'])

        except Auction.DoesNotExist:
            raise

        Notification.objects.create(
            user=auction.product.owner,
            title='مزايدة جديدة على مزادك',
            message=f'قام {user.username} بالمزايدة بمبلغ {amount} جنيه على مزادك "{auction.product.title}".',
            related_product=auction.product,
            related_auction=auction,
            notification_type='info',
        )

        return bid, auction

    @staticmethod
    def place_bid_from_notification(user, notif):
        auction = notif.related_auction
        product = notif.related_product

        if not auction:
            raise AuctionBidError({'error': 'المزاد مش موجود'}, status_code=400)

        if not auction.is_active:
            notif.is_approved = False
            notif.save(update_fields=['is_approved'])
            raise AuctionBidError({'error': 'المزاد انتهى خلاص'}, status_code=400)

        if auction.end_time < timezone.now():
            auction.is_active = False
            auction.save(update_fields=['is_active'])
            notif.is_approved = False
            notif.save(update_fields=['is_approved'])
            raise AuctionBidError({'error': 'المزاد انتهى خلاص'}, status_code=400)

        bid_amount = notif.suggested_bid
        if bid_amount is None or bid_amount <= auction.current_bid:
            from ..serializers import _calc_bid_increment
            bid_amount = auction.current_bid + _calc_bid_increment(auction.current_bid)

        if product and product.owner == user:
            raise AuctionBidError(
                {'error': 'لا يمكنك المزايدة على مزادك الخاص'},
                status_code=400,
            )

        hold_description = f'حجز مزايدة (موافقة وكيل ذكي): "{auction.product.title}"'

        try:
            with transaction.atomic():
                auction = (
                    Auction.objects
                    .select_for_update()
                    .get(id=auction.id)
                )

                if not auction.is_active or auction.end_time < timezone.now():
                    notif.is_approved = False
                    notif.save(update_fields=['is_approved'])
                    raise AuctionBidError({'error': 'المزاد انتهى خلاص'}, status_code=400)

                if bid_amount <= auction.current_bid:
                    from ..serializers import _calc_bid_increment
                    bid_amount = auction.current_bid + _calc_bid_increment(auction.current_bid)

                profile = (
                    UserProfile.objects
                    .select_for_update()
                    .get(user=user)
                )

                previous_bid = (
                    Bid.objects
                    .filter(auction=auction, bidder=user)
                    .order_by('-amount')
                    .first()
                )
                needed = bid_amount - previous_bid.amount if previous_bid else bid_amount

                if profile.wallet_balance < needed:
                    raise AuctionBidError(
                        {
                            'error': (
                                f'رصيدك غير كافي للمزايدة. رصيدك: {profile.wallet_balance} جنيه، '
                                f'والمطلوب: {needed} جنيه.'
                            ),
                            'insufficient_balance': True,
                            'current_balance': float(profile.wallet_balance),
                            'required': float(needed),
                        },
                        status_code=400,
                    )

                WalletService.hold_bid_amount(
                    profile,
                    auction,
                    bid_amount,
                    previous_bid_amount=previous_bid.amount if previous_bid else None,
                    hold_description=hold_description,
                )

                bid = Bid.objects.create(
                    auction=auction,
                    bidder=user,
                    amount=bid_amount,
                )

                auction.current_bid = bid_amount
                auction.highest_bidder = user
                auction.save(update_fields=['current_bid', 'highest_bidder'])

                notif.is_approved = True
                notif.is_read = True
                notif.save(update_fields=['is_approved', 'is_read'])

        except Auction.DoesNotExist:
            raise

        Notification.objects.create(
            user=user,
            title=f'✅ تم المزايدة بنجاح على: {auction.product.title}',
            message=(
                f'وافقت على مزايدة الوكيل الذكي بمبلغ {bid_amount} جنيه '
                f'على "{auction.product.title}".'
            ),
            related_product=auction.product,
            related_auction=auction,
            notification_type='info',
        )

        Notification.objects.create(
            user=auction.product.owner,
            title='مزايدة جديدة على مزادك',
            message=f'قام {user.username} بالمزايدة بمبلغ {bid_amount} جنيه على مزادك "{auction.product.title}".',
            related_product=auction.product,
            related_auction=auction,
            notification_type='info',
        )

        return bid, auction, bid_amount
