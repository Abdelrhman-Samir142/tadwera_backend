from ..models import Notification


class NotificationService:

    @staticmethod
    def list_for_user(user, limit=50):
        return Notification.objects.filter(user=user)[:limit]

    @staticmethod
    def mark_all_read(user):
        return Notification.objects.filter(user=user, is_read=False).update(is_read=True)

    @staticmethod
    def unread_count(user):
        return Notification.objects.filter(user=user, is_read=False).count()

    @staticmethod
    def delete_all(user):
        deleted_count, _ = Notification.objects.filter(user=user).delete()
        return deleted_count

    @staticmethod
    def respond_to_bid_approval(user, notif, action):
        from ..models import Auction, UserProfile
        from .auction import AuctionBidError, AuctionService

        if notif.notification_type != 'bid_approval':
            return {'error': 'هذا الإشعار مش من نوع طلب موافقة'}, 400

        if notif.is_approved is not None:
            action_label = 'وافقت' if notif.is_approved else 'رفضت'
            return {'error': f'أنت {action_label} على الإشعار ده قبل كده'}, 400

        if action not in ('approve', 'reject'):
            return {'error': 'الإجراء لازم يكون approve أو reject'}, 400

        if action == 'reject':
            notif.is_approved = False
            notif.is_read = True
            notif.save(update_fields=['is_approved', 'is_read'])
            return {'status': 'rejected', 'message': 'تم رفض المزايدة'}, 200

        try:
            _, _, bid_amount = AuctionService.place_bid_from_notification(user, notif)
        except Auction.DoesNotExist:
            return {'error': 'المزاد غير موجود'}, 404
        except UserProfile.DoesNotExist:
            return {'error': 'الملف الشخصي غير موجود'}, 400
        except AuctionBidError as e:
            return e.payload, e.status_code

        return {
            'status': 'approved',
            'bid_amount': float(bid_amount),
            'message': f'تم المزايدة بنجاح بمبلغ {bid_amount} جنيه',
        }, 200
