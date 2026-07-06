from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import UserProfile, WalletTransaction


class WalletService:

    @staticmethod
    def build_topup_response(new_balance, amount):
        return {
            'status': 'success',
            'new_balance': float(new_balance),
            'amount_added': float(amount),
        }

    @staticmethod
    def validate_topup_amount(amount_raw):
        if amount_raw is None:
            raise ValidationError('المبلغ مطلوب')

        try:
            amount = Decimal(str(amount_raw))
        except Exception:
            raise ValidationError('مبلغ غير صالح')

        if amount <= 0:
            raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')

        if amount > 10000:
            raise ValidationError('الحد الأقصى للشحن الواحد 10,000 جنيه')

        return amount

    @staticmethod
    def topup(user, amount):
        with transaction.atomic():
            profile = (
                UserProfile.objects
                .select_for_update()
                .get(user=user)
            )
            profile.wallet_balance += amount
            profile.save(update_fields=['wallet_balance'])

            WalletService.record_transaction(
                user=user,
                amount=amount,
                transaction_type='topup',
                description=f'شحن رصيد: {amount} جنيه',
                balance_after=profile.wallet_balance,
            )

        return profile.wallet_balance

    @staticmethod
    def record_transaction(
        user,
        amount,
        transaction_type,
        description,
        balance_after,
        related_auction=None,
        product=None,
    ):
        create_kwargs = {
            'user': user,
            'transaction_type': transaction_type,
            'amount': amount,
            'balance_after': balance_after,
            'description': description,
        }
        if related_auction is not None:
            create_kwargs['related_auction'] = related_auction
        return WalletTransaction.objects.create(**create_kwargs)

    @staticmethod
    def refund_bid_amount(user, amount, auction, description, profile=None):
        if profile is None:
            profile = user.profile

        profile.wallet_balance += amount
        profile.save(update_fields=['wallet_balance'])
        WalletService.record_transaction(
            user=user,
            amount=amount,
            transaction_type='bid_refund',
            description=description,
            balance_after=profile.wallet_balance,
            related_auction=auction,
        )
        return profile

    @staticmethod
    def hold_bid_amount(
        profile,
        auction,
        amount,
        previous_bid_amount=None,
        hold_description=None,
        refund_description=None,
    ):
        if previous_bid_amount:
            profile.wallet_balance += previous_bid_amount
            WalletService.record_transaction(
                user=profile.user,
                amount=previous_bid_amount,
                transaction_type='bid_refund',
                description=refund_description or f'استرداد مزايدة سابقة: "{auction.product.title}"',
                balance_after=profile.wallet_balance,
                related_auction=auction,
            )

        profile.wallet_balance -= amount
        profile.save(update_fields=['wallet_balance'])
        WalletService.record_transaction(
            user=profile.user,
            amount=amount,
            transaction_type='bid_hold',
            description=hold_description or f'حجز مزايدة: "{auction.product.title}"',
            balance_after=profile.wallet_balance,
            related_auction=auction,
        )
        return profile

    @staticmethod
    def transfer_purchase_funds(buyer, seller, price, product_title):
        buyer_profile = (
            UserProfile.objects
            .select_for_update()
            .get(user=buyer)
        )
        seller_profile = (
            UserProfile.objects
            .select_for_update()
            .get(user=seller)
        )

        buyer_profile.wallet_balance -= price
        buyer_profile.save(update_fields=['wallet_balance'])
        WalletService.record_transaction(
            user=buyer,
            amount=price,
            transaction_type='purchase',
            description=f'شراء منتج: "{product_title}"',
            balance_after=buyer_profile.wallet_balance,
        )

        seller_profile.wallet_balance += price
        seller_profile.total_sales = (seller_profile.total_sales or 0) + 1
        seller_profile.save(update_fields=['wallet_balance', 'total_sales'])
        WalletService.record_transaction(
            user=seller,
            amount=price,
            transaction_type='sale',
            description=f'بيع منتج: "{product_title}" للمشتري {buyer.username}',
            balance_after=seller_profile.wallet_balance,
        )

        return buyer_profile, seller_profile

    @staticmethod
    def get_transaction_history(user, limit=50):
        transactions = WalletTransaction.objects.filter(user=user)[:limit]
        data = []
        for t in transactions:
            data.append({
                'id': t.id,
                'type': t.transaction_type,
                'type_label': dict(WalletTransaction.TRANSACTION_TYPES).get(
                    t.transaction_type, t.transaction_type
                ),
                'amount': float(t.amount),
                'balance_after': float(t.balance_after),
                'description': t.description,
                'created_at': t.created_at.isoformat(),
            })
        return data
