from django.contrib import admin
from .models import UserProfile, Product, ProductImage, Auction, Bid, Conversation, Message, UserAgent, Notification


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'city', 'trust_score', 'is_verified', 'total_sales', 'created_at']
    list_filter = ['is_verified', 'city']
    search_fields = ['user__username', 'user__email', 'phone']
    readonly_fields = ['created_at', 'updated_at']


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['title', 'owner', 'category', 'price', 'status', 'is_auction', 'created_at']
    list_filter = ['category', 'condition', 'status', 'is_auction', 'created_at']
    search_fields = ['title', 'description', 'owner__username']
    readonly_fields = ['views_count', 'created_at', 'updated_at']
    inlines = [ProductImageInline]


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ['product', 'current_bid', 'highest_bidder', 'end_time', 'is_active']
    list_filter = ['is_active', 'end_time']
    search_fields = ['product__title']
    readonly_fields = ['created_at']


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ['auction', 'bidder', 'amount', 'created_at']
    list_filter = ['created_at']
    search_fields = ['auction__product__title', 'bidder__username']
    readonly_fields = ['created_at']


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ['sender', 'content', 'is_read', 'created_at']


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['product', 'buyer', 'seller', 'created_at', 'updated_at']
    list_filter = ['created_at']
    search_fields = ['product__title', 'buyer__username', 'seller__username']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['conversation', 'sender', 'short_content', 'is_read', 'created_at']
    list_filter = ['is_read', 'created_at']
    search_fields = ['content', 'sender__username']
    readonly_fields = ['created_at']

    def short_content(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    short_content.short_description = 'Content'


@admin.register(UserAgent)
class UserAgentAdmin(admin.ModelAdmin):
    list_display = ['user', 'target_item', 'max_budget', 'is_active', 'created_at']
    list_filter = ['is_active', 'target_item']
    search_fields = ['user__username', 'target_item']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'title', 'is_read', 'related_product', 'created_at']
    list_filter = ['is_read', 'created_at']
    search_fields = ['user__username', 'title', 'message']
    readonly_fields = ['created_at']
