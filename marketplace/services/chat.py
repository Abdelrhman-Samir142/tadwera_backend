from django.core.exceptions import ValidationError
from django.db import models
from rest_framework.exceptions import PermissionDenied

from ..models import Conversation, Message, Product


class ChatService:

    @staticmethod
    def get_user_conversations_queryset(user):
        return Conversation.objects.filter(
            models.Q(buyer=user) | models.Q(seller=user)
        ).select_related(
            'product', 'buyer', 'seller', 'buyer__profile', 'seller__profile'
        ).prefetch_related('messages', 'product__images')

    @staticmethod
    def send_winner_message(auction):
        """Send a congratulations message to the auction winner via the chat system"""
        try:
            conversation, _ = Conversation.objects.get_or_create(
                product=auction.product,
                buyer=auction.highest_bidder,
                defaults={'seller': auction.product.owner}
            )
            Message.objects.create(
                conversation=conversation,
                sender=auction.product.owner,
                content=f'🎉 تهانينا! لقد فزت بالمزاد على "{auction.product.title}" بمبلغ {auction.current_bid} جنيه. تواصل مع البائع لإتمام عملية الشراء.'
            )
        except Exception as e:
            import traceback
            traceback.print_exc()

    @staticmethod
    def mark_conversation_read(conversation, reader):
        conversation.messages.filter(is_read=False).exclude(sender=reader).update(is_read=True)

    @staticmethod
    def start_or_get_conversation(buyer, product_id):
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            raise

        if product.owner == buyer:
            raise ValidationError('Cannot start a conversation with yourself')

        conversation, created = Conversation.objects.get_or_create(
            product=product,
            buyer=buyer,
            defaults={'seller': product.owner}
        )
        return conversation, created

    @staticmethod
    def send_message(conversation, sender, content):
        if sender not in [conversation.buyer, conversation.seller]:
            raise PermissionDenied('You are not a participant in this conversation')

        message = Message.objects.create(
            conversation=conversation,
            sender=sender,
            content=content
        )

        conversation.save()

        return message

    @staticmethod
    def get_unread_count(user):
        return Message.objects.filter(
            conversation__in=Conversation.objects.filter(
                models.Q(buyer=user) | models.Q(seller=user)
            ),
            is_read=False
        ).exclude(sender=user).count()

    @staticmethod
    def delete_conversation(conversation, user):
        if user not in [conversation.buyer, conversation.seller]:
            raise PermissionDenied('You are not a participant in this conversation')

        conversation.delete()

    @staticmethod
    def delete_message(message, user):
        if message.sender != user:
            raise PermissionDenied('You can only delete your own messages')

        message.delete()

    @staticmethod
    def edit_message(message, user, content):
        if message.sender != user:
            raise PermissionDenied('You can only edit your own messages')

        message.content = content
        message.save()
        return message
