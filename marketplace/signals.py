"""
Marketplace signals.
- Auto-creates UserProfile when a User is created (including superusers).
- Triggers agent discovery when a new direct-sale product is created.
"""

import logging
import threading
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import connection
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


# ── Auto-create UserProfile for every new User ──────────────────────────────
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Automatically create a UserProfile whenever a new User is created.
    This covers users created via `createsuperuser`, Django admin, or any
    other method that bypasses the register_view serializer.
    """
    if created:
        from marketplace.models import UserProfile
        # Don't create if it already exists (e.g. register_view already created it)
        if not UserProfile.objects.filter(user=instance).exists():
            role = 'admin' if (instance.is_superuser or instance.is_staff) else 'user'
            UserProfile.objects.create(
                user=instance,
                role=role,
                city='',  # Default empty; superusers can update later
            )
            logger.info(f"[Signal] Auto-created UserProfile for '{instance.username}' (role={role})")


def _run_discovery_in_background(product_id):
    """Run agent discovery in a background thread."""
    try:
        from marketplace.serializers import run_agent_discovery_async
        run_agent_discovery_async(product_id)
    except Exception as e:
        logger.error(f"[Marketplace/Signal] Discovery failed for product #{product_id}: {e}")
    finally:
        connection.close()


@receiver(post_save, sender='marketplace.Product')
def trigger_agent_discovery(sender, instance, created, **kwargs):
    """
    DISABLED — Agent now only works for AUCTIONS.
    Non-auction (store) products are completely ignored by the agent.
    Auction products are handled by run_auto_bidding in ProductCreateSerializer.
    """
    # Agent discovery for non-auction products is disabled.
    # All agent logic now runs only for auctions via run_auto_bidding.
    return


# ── WebSocket Broadcast Signals ─────────────────────────────────────────────
# These signals push new messages and notifications to connected WebSocket
# clients in real-time. They fire on every Message/Notification creation,
# regardless of where in the codebase the .objects.create() was called.

@receiver(post_save, sender='marketplace.Message')
def broadcast_new_message(sender, instance, created, **kwargs):
    """
    When a new Message is saved, broadcast it to the chat_{conversation_id}
    WebSocket group so all connected participants see it instantly.
    """
    if not created:
        return

    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        group_name = f"chat_{instance.conversation_id}"

        avatar_url = None
        try:
            if hasattr(instance.sender, 'profile') and instance.sender.profile.avatar:
                avatar_url = instance.sender.profile.avatar.url
        except Exception:
            pass

        message_data = {
            "id": instance.id,
            "conversation": instance.conversation_id,
            "sender": instance.sender_id,
            "sender_name": instance.sender.username,
            "sender_avatar": avatar_url,
            "content": instance.content,
            "is_read": instance.is_read,
            "created_at": instance.created_at.isoformat(),
        }

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "chat_message",
                "message": message_data,
            },
        )
    except Exception as e:
        logger.error(f"[Signal/WS] Failed to broadcast message: {e}")


@receiver(post_save, sender='marketplace.Notification')
def broadcast_new_notification(sender, instance, created, **kwargs):
    """
    When a new Notification is saved, broadcast it to the
    notifications_{user_id} WebSocket group so the user sees it instantly.
    """
    if not created:
        return

    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        group_name = f"notifications_{instance.user_id}"

        notification_data = {
            "id": instance.id,
            "title": instance.title,
            "message": instance.message,
            "is_read": instance.is_read,
            "notification_type": instance.notification_type,
            "related_product_id": instance.related_product_id,
            "related_auction_id": instance.related_auction_id,
            "created_at": instance.created_at.isoformat(),
        }

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "new_notification",
                "notification": notification_data,
            },
        )
    except Exception as e:
        logger.error(f"[Signal/WS] Failed to broadcast notification: {e}")
