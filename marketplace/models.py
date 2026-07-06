from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from django.core.exceptions import ValidationError
from pgvector.django import VectorField

def validate_image_size(value):
    filesize = value.size
    # 5MB max size
    if filesize > 5 * 1024 * 1024:
        raise ValidationError("حجم الصورة يجب أن لا يتجاوز 5 ميجابايت")


class UserProfile(models.Model):
    """Extended user profile with verification and location"""
    ROLE_CHOICES = [
        ('user', 'User'),
        ('admin', 'Admin'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    phone = models.CharField(max_length=15, blank=True)
    city = models.CharField(max_length=100, blank=True, default='')
    trust_score = models.IntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    is_verified = models.BooleanField(default=False)
    avatar = models.ImageField(
        upload_to='avatars/', 
        blank=True, 
        null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp']),
            validate_image_size
        ]
    )
    wallet_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_sales = models.IntegerField(default=0)
    seller_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_profiles'
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f"{self.user.username}'s Profile"


class SellerRating(models.Model):
    """Individual ratings to track which user rated whom to prevent duplicates"""
    seller = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='ratings')
    rater = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_ratings')
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'seller_ratings'
        unique_together = ('seller', 'rater')
        verbose_name = 'Seller Rating'
        verbose_name_plural = 'Seller Ratings'

    def __str__(self):
        return f"{self.rater.username} rated {self.seller.user.username} - {self.rating} stars"


class Product(models.Model):
    """Main product model for marketplace listings"""
    
    CATEGORY_CHOICES = [
        ('scrap_metals', 'خردة ومعادن'),
        ('electronics', 'إلكترونيات وأجهزة'),
        ('appliances', 'أجهزة منزلية'),
        ('furniture', 'أثاث وديكور'),
        ('cars', 'سيارات للبيع'),
        ('real_estate', 'عقارات'),
        ('books', 'كتب'),
        ('other', 'أخرى'),
    ]
    
    CONDITION_CHOICES = [
        ('new', 'New'),
        ('like-new', 'Like New'),
        ('good', 'Good'),
        ('fair', 'Fair'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('sold', 'Sold'),
        ('pending', 'Pending'),
        ('inactive', 'Inactive'),
    ]
    
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='products')
    title = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    condition = models.CharField(max_length=10, choices=CONDITION_CHOICES, default='good')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    location = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20, blank=True, default='')
    is_auction = models.BooleanField(default=False)
    detected_item = models.CharField(max_length=100, blank=True, default='', help_text='YOLO detected class name for agent matching')
    auction_end_time = models.DateTimeField(null=True, blank=True)
    views_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'products'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category', 'status']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return self.title


class ProductImage(models.Model):
    """Product images - supporting multiple images per product"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(
        upload_to='products/',
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp']),
            validate_image_size
        ]
    )
    is_primary = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'product_images'
        ordering = ['order', '-is_primary']
    
    def __str__(self):
        return f"Image for {self.product.title}"


class Auction(models.Model):
    """Auction model linked to products"""
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='auction')
    starting_bid = models.DecimalField(max_digits=10, decimal_places=2)
    current_bid = models.DecimalField(max_digits=10, decimal_places=2)
    highest_bidder = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='won_auctions')
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'auctions'
        ordering = ['end_time']
    
    def __str__(self):
        return f"Auction for {self.product.title}"


class Bid(models.Model):
    """Individual bids on auctions"""
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='bids')
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bids')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'bids'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['auction', '-amount']),
        ]
    
    def __str__(self):
        return f"Bid of {self.amount} by {self.bidder.username}"


class Conversation(models.Model):
    """Chat conversation between buyer and seller about a product"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='conversations')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations_as_buyer')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations_as_seller')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'conversations'
        ordering = ['-updated_at']
        unique_together = ['product', 'buyer']

    def __str__(self):
        return f"Chat: {self.buyer.username} → {self.seller.username} about {self.product.title}"


class Message(models.Model):
    """Individual message within a conversation"""
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]

    def __str__(self):
        return f"{self.sender.username}: {self.content[:50]}"


class Wishlist(models.Model):
    """User's favorite/saved products"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlisted_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wishlists'
        unique_together = ['user', 'product']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.product.title}"


class UserAgent(models.Model):
    """
    AI Auto-Bidder agent configuration.
    Each user can set up agents that watch for specific YOLO-detected items
    and automatically bid on auctions matching that item.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agents')
    target_item = models.CharField(
        max_length=50,
        help_text="Raw YOLO class name to watch for (e.g., 'washing_machine', 'scrap_metal')"
    )
    max_budget = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(1)],
        help_text="Maximum amount the agent is allowed to bid"
    )
    requirements_prompt = models.TextField(
        blank=True, default='',
        help_text="User's natural language requirements (e.g., 'Toshiba 10kg good condition')"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_agents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['target_item', 'is_active']),
        ]

    def __str__(self):
        status = '✅' if self.is_active else '❌'
        return f"{status} {self.user.username} → {self.target_item} (max {self.max_budget})"


class Notification(models.Model):
    """Notification for agent actions and other system events"""
    NOTIFICATION_TYPES = [
        ('info', 'Info'),                  # Regular notification
        ('bid_approval', 'Bid Approval'),  # Requires user approval to place bid
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    related_product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    related_auction = models.ForeignKey('Auction', on_delete=models.SET_NULL, null=True, blank=True)
    reasoning = models.TextField(blank=True, default='', help_text="AI reasoning for match or rejection")
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='info')
    is_approved = models.BooleanField(null=True, blank=True, default=None, help_text="User's response to bid_approval: True=approved, False=rejected, None=pending")
    suggested_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Suggested bid amount for bid_approval notifications")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.title}"


class WalletTransaction(models.Model):
    """Track all wallet operations: topups, bid holds, refunds, and deductions"""
    TRANSACTION_TYPES = [
        ('topup', 'شحن رصيد'),
        ('bid_hold', 'حجز مزايدة'),
        ('bid_refund', 'استرداد مزايدة'),
        ('bid_deduct', 'خصم فوز مزايدة'),
        ('purchase', 'شراء مباشر'),
        ('sale', 'بيع مباشر'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wallet_transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.CharField(max_length=300, blank=True, default='')
    related_auction = models.ForeignKey('Auction', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wallet_transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} | {self.transaction_type} | {self.amount}"


class Order(models.Model):
    """Record of a completed direct-sale purchase."""
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders_as_buyer')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders_as_seller')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='orders')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['buyer', '-created_at']),
            models.Index(fields=['seller', '-created_at']),
        ]

    def __str__(self):
        return f"Order #{self.id}: {self.buyer.username} → {self.seller.username} ({self.amount})"


class ProductVisualEmbedding(models.Model):
    """
    Stores a CLIP image embedding for each product's primary image.
    Used for Visual Search (find similar products by uploading a photo).
    The vector is stored as a JSON array of 512 floats (CLIP ViT-B/32).
    """
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='visual_embedding',
        primary_key=True,
    )
    embedding = VectorField(
        dimensions=2048,
        help_text="2048-dim Vision embedding from Nemotron",
        null=True,
        blank=True
    )
    image_url = models.URLField(
        max_length=500,
        help_text="URL of the image that was embedded"
    )
    model_name = models.CharField(max_length=100, default='openai/clip-vit-base-patch32')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'product_visual_embeddings'
        verbose_name = 'Product Visual Embedding'
        verbose_name_plural = 'Product Visual Embeddings'

    def __str__(self):
        return f"Visual Embedding for Product #{self.product_id}"


class AgentPendingBid(models.Model):
    """
    Holds an AI-proposed bid awaiting user approval.
    No wallet deduction or Bid creation happens until the user approves.
    Delta deduction: on approval, only (proposed_amount - previous_amount) is charged.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]

    agent = models.ForeignKey(
        'UserAgent', on_delete=models.CASCADE, related_name='pending_bids'
    )
    auction = models.ForeignKey(
        'Auction', on_delete=models.CASCADE, related_name='pending_bids'
    )
    proposed_amount = models.DecimalField(max_digits=10, decimal_places=2)
    previous_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Amount the agent previously had locked in this auction (for delta calc)"
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending'
    )
    ai_reasoning = models.TextField(blank=True, default='')
    notification = models.ForeignKey(
        'Notification', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pending_bids'
    )
    is_counter_bid = models.BooleanField(
        default=False,
        help_text="True when this is a reaction to being outbid (outbid scenario)"
    )
    round_number = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_pending_bids'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['agent', 'status']),
            models.Index(fields=['auction', 'status']),
        ]

    def __str__(self):
        return (
            f"PendingBid [{self.status}] agent={self.agent_id} "
            f"auction={self.auction_id} amount={self.proposed_amount}"
        )
