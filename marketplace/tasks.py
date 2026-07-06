"""
Celery tasks for RefurbAI marketplace.
Periodic background jobs for auction management.
"""
import logging
from celery import shared_task
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(name='marketplace.close_expired_auctions')
def close_expired_auctions_task():
    """
    Celery Beat task: close all auctions whose end_time has passed.
    Runs every 60 seconds via CELERY_BEAT_SCHEDULE.

    Uses select_for_update to avoid racing with place_bid.
    """
    from marketplace.models import Auction, Bid, WalletTransaction, UserProfile
    from marketplace.models import Conversation, Message

    now = timezone.now()
    expired_ids = list(
        Auction.objects.filter(is_active=True, end_time__lte=now)
        .values_list('id', flat=True)
    )

    if not expired_ids:
        return f"0 auctions expired"

    closed = 0
    for auction_id in expired_ids:
        try:
            with transaction.atomic():
                auction = (
                    Auction.objects
                    .select_for_update()
                    .select_related('product', 'product__owner', 'highest_bidder')
                    .get(id=auction_id)
                )

                # Double-check under lock
                if not auction.is_active or auction.end_time > now:
                    continue

                auction.is_active = False
                auction.save(update_fields=['is_active'])

                auction.product.status = 'sold'
                auction.product.save(update_fields=['status'])

                # ── Wallet: Refund losers & keep winner hold ──
                winner = auction.highest_bidder
                all_bids = (
                    auction.bids
                    .select_related('bidder', 'bidder__profile')
                    .order_by('-amount')
                )

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
                        # Winner: hold stays — log deduct transaction
                        WalletTransaction.objects.create(
                            user=bidder,
                            transaction_type='bid_deduct',
                            amount=bid.amount,
                            balance_after=profile.wallet_balance,
                            description=f'خصم فوز مزاد: "{auction.product.title}"',
                            related_auction=auction,
                        )
                        # Transfer to seller
                        try:
                            seller_profile = (
                                UserProfile.objects
                                .select_for_update()
                                .get(user=auction.product.owner)
                            )
                            seller_profile.wallet_balance += bid.amount
                            seller_profile.total_sales = (seller_profile.total_sales or 0) + 1
                            seller_profile.save(update_fields=['wallet_balance', 'total_sales'])
                            WalletTransaction.objects.create(
                                user=auction.product.owner,
                                transaction_type='topup',
                                amount=bid.amount,
                                balance_after=seller_profile.wallet_balance,
                                description=f'بيع مزاد: "{auction.product.title}" - الفائز: {bidder.username}',
                                related_auction=auction,
                            )
                        except UserProfile.DoesNotExist:
                            pass
                    else:
                        # Loser: refund
                        loser_profile = (
                            UserProfile.objects
                            .select_for_update()
                            .get(user=bidder)
                        )
                        loser_profile.wallet_balance += bid.amount
                        loser_profile.save(update_fields=['wallet_balance'])
                        WalletTransaction.objects.create(
                            user=bidder,
                            transaction_type='bid_refund',
                            amount=bid.amount,
                            balance_after=loser_profile.wallet_balance,
                            description=f'استرداد مزايدة: "{auction.product.title}"',
                            related_auction=auction,
                        )

                # Send winner message
                if winner:
                    try:
                        conversation, _ = Conversation.objects.get_or_create(
                            product=auction.product,
                            buyer=winner,
                            defaults={'seller': auction.product.owner}
                        )
                        Message.objects.create(
                            conversation=conversation,
                            sender=auction.product.owner,
                            content=(
                                f'🎉 تهانينا! لقد فزت بالمزاد على "{auction.product.title}" '
                                f'بمبلغ {auction.current_bid} جنيه. '
                                f'تواصل مع البائع لإتمام عملية الشراء.'
                            ),
                        )
                    except Exception:
                        logger.exception("[CeleryAuction] Failed to send winner message")

                closed += 1

        except Auction.DoesNotExist:
            continue
        except Exception:
            logger.exception(f"[CeleryAuction] Error closing auction {auction_id}")

    logger.info(f"[CeleryAuction] Closed {closed}/{len(expired_ids)} expired auctions")
    return f"Closed {closed} auctions"
