"""
WebSocket consumers for real-time chat and notifications.

ChatConsumer:
  ws/chat/<conversation_id>/  — real-time messaging within a conversation

NotificationConsumer:
  ws/notifications/  — real-time notification push to authenticated users
"""

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for real-time chat within a Conversation.

    - On connect: validates user is a participant, joins the channel group.
    - On receive: saves message to DB, broadcasts to all participants.
    - On disconnect: leaves the channel group.
    """

    async def connect(self):
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.room_group_name = f"chat_{self.conversation_id}"
        user = self.scope.get("user", AnonymousUser())

        # Reject unauthenticated users
        if not user or not user.is_authenticated:
            logger.info(f"[WS/Chat] Rejected unauthenticated connection to conversation {self.conversation_id}")
            await self.close()
            return

        # Verify user is a participant in this conversation
        is_participant = await self._check_participant(user, self.conversation_id)
        if not is_participant:
            logger.info(f"[WS/Chat] User {user.username} is not a participant in conversation {self.conversation_id}")
            await self.close()
            return

        # Join the channel group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )
        await self.accept()
        logger.info(f"[WS/Chat] {user.username} connected to conversation {self.conversation_id}")

        # Mark messages as read for this user
        await self._mark_read(user, self.conversation_id)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name,
        )

    async def receive_json(self, content):
        """Handle incoming message from WebSocket client."""
        user = self.scope.get("user", AnonymousUser())
        if not user or not user.is_authenticated:
            return

        message_text = content.get("message", "").strip()
        if not message_text:
            return

        # Save message to database
        message_data = await self._save_message(user, self.conversation_id, message_text)

        if message_data:
            # Broadcast to all participants in this conversation
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "message": message_data,
                },
            )

    async def chat_message(self, event):
        """Handle chat_message event from channel layer — send to WebSocket."""
        await self.send_json({
            "type": "chat_message",
            "message": event["message"],
        })

    @database_sync_to_async
    def _check_participant(self, user, conversation_id):
        from django.db.models import Q
        from marketplace.models import Conversation
        return Conversation.objects.filter(
            Q(id=conversation_id),
            Q(buyer=user) | Q(seller=user),
        ).exists()

    @database_sync_to_async
    def _mark_read(self, user, conversation_id):
        from marketplace.models import Conversation
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            conversation.messages.filter(is_read=False).exclude(sender=user).update(is_read=True)
        except Conversation.DoesNotExist:
            pass

    @database_sync_to_async
    def _save_message(self, user, conversation_id, content):
        from marketplace.models import Conversation, Message
        try:
            conversation = Conversation.objects.get(id=conversation_id)

            # Verify user is still a participant
            if user not in [conversation.buyer, conversation.seller]:
                return None

            message = Message.objects.create(
                conversation=conversation,
                sender=user,
                content=content,
            )
            # Touch conversation updated_at
            conversation.save()

            avatar_url = None
            try:
                if hasattr(user, 'profile') and user.profile.avatar:
                    avatar_url = user.profile.avatar.url
            except Exception:
                pass

            return {
                "id": message.id,
                "conversation": conversation.id,
                "sender": user.id,
                "sender_name": user.username,
                "sender_avatar": avatar_url,
                "content": message.content,
                "is_read": False,
                "created_at": message.created_at.isoformat(),
            }
        except Conversation.DoesNotExist:
            logger.error(f"[WS/Chat] Conversation {conversation_id} not found")
            return None
        except Exception as e:
            logger.error(f"[WS/Chat] Error saving message: {e}")
            return None


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for real-time notification delivery.

    - On connect: joins a personal notification group.
    - Read-only: client only receives, never sends.
    - Notifications are pushed via Django signals when Notification objects are created.
    """

    async def connect(self):
        user = self.scope.get("user", AnonymousUser())

        if not user or not user.is_authenticated:
            logger.info("[WS/Notif] Rejected unauthenticated notification connection")
            await self.close()
            return

        self.notification_group_name = f"notifications_{user.id}"

        await self.channel_layer.group_add(
            self.notification_group_name,
            self.channel_name,
        )
        await self.accept()
        logger.info(f"[WS/Notif] {user.username} connected to notifications")

    async def disconnect(self, close_code):
        if hasattr(self, "notification_group_name"):
            await self.channel_layer.group_discard(
                self.notification_group_name,
                self.channel_name,
            )

    async def receive_json(self, content):
        """Notification channel is read-only — ignore client messages."""
        pass

    async def new_notification(self, event):
        """Handle new_notification event from channel layer — send to WebSocket."""
        await self.send_json({
            "type": "new_notification",
            "notification": event["notification"],
        })
