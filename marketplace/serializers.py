from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone
from .models import UserProfile, Product, ProductImage, Auction, Bid, Conversation, Message, UserAgent, Notification, WalletTransaction, Order, AgentPendingBid

import logging
logger = logging.getLogger(__name__)


class UserSerializer(serializers.ModelSerializer):
    """User serializer for authentication responses"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']


class UserProfileSerializer(serializers.ModelSerializer):
    """User profile serializer"""
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = UserProfile
        fields = [
            'id', 'user', 'role', 'phone', 'city', 'trust_score', 
            'is_verified', 'avatar', 'wallet_balance', 
            'total_sales', 'seller_rating', 'created_at'
        ]
        read_only_fields = ['id', 'role', 'trust_score', 'wallet_balance', 'total_sales', 'seller_rating', 'created_at']

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        
        # Hide wallet_balance if requesting user is not the owner and not an admin
        if request and request.user.is_authenticated:
            is_admin = request.user.is_staff or request.user.is_superuser
            try:
                if hasattr(request.user, 'profile') and request.user.profile.role == 'admin':
                    is_admin = True
            except Exception:
                pass
                
            if instance.user != request.user and not is_admin:
                ret.pop('wallet_balance', None)
        else:
            ret.pop('wallet_balance', None)
            
        return ret


class ProductImageSerializer(serializers.ModelSerializer):
    """Product image serializer"""
    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'is_primary', 'order']
        read_only_fields = ['id']


class BidSerializer(serializers.ModelSerializer):
    """Bid serializer with bidder info"""
    bidder_name = serializers.CharField(source='bidder.username', read_only=True)
    bidder_avatar = serializers.SerializerMethodField()
    
    class Meta:
        model = Bid
        fields = ['id', 'auction', 'bidder', 'bidder_name', 'bidder_avatar', 'amount', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_bidder_avatar(self, obj):
        """Safely return avatar URL — returns None if avatar is missing or broken."""
        try:
            avatar = obj.bidder.profile.avatar
            if avatar and hasattr(avatar, 'url'):
                return avatar.url
        except Exception:
            pass
        return None

    def validate_amount(self, value):
        """Ensure bid amount is strictly greater than the auction's current bid."""
        from decimal import Decimal
        if value <= Decimal('0'):
            raise serializers.ValidationError('مبلغ المزايدة يجب أن يكون أكبر من صفر')

        # When used in a create context with auction data available
        auction = None
        if 'auction' in self.initial_data:
            try:
                from .models import Auction
                auction = Auction.objects.get(id=self.initial_data['auction'])
            except (Auction.DoesNotExist, ValueError, TypeError):
                pass

        # If we're validating inside a view that already set the instance
        if auction is None and self.instance and hasattr(self.instance, 'auction'):
            auction = self.instance.auction

        if auction is not None and value <= auction.current_bid:
            raise serializers.ValidationError(
                f'يجب أن تكون المزايدة أعلى من السعر الحالي ({auction.current_bid} جنيه)'
            )
        return value



class AuctionSerializer(serializers.ModelSerializer):
    """Auction serializer with bidding history"""
    bids = BidSerializer(many=True, read_only=True)
    highest_bidder_name = serializers.CharField(source='highest_bidder.username', read_only=True, allow_null=True)
    total_bids = serializers.SerializerMethodField()
    product_title = serializers.CharField(source='product.title', read_only=True)
    product_image = serializers.SerializerMethodField()
    
    class Meta:
        model = Auction
        fields = [
            'id', 'product', 'product_title', 'product_image',
            'starting_bid', 'current_bid', 'highest_bidder', 
            'highest_bidder_name', 'start_time', 'end_time', 
            'is_active', 'total_bids', 'bids', 'created_at'
        ]
        read_only_fields = ['id', 'current_bid', 'highest_bidder', 'created_at']

    def get_total_bids(self, obj):
        return obj.bids.count()

    def get_product_image(self, obj):
        primary_img = obj.product.images.filter(is_primary=True).first()
        if primary_img:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary_img.image.url)
        return None


class ProductListSerializer(serializers.ModelSerializer):
    """Lightweight product serializer for list views"""
    owner_name = serializers.CharField(source='owner.username', read_only=True)
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    primary_image = serializers.SerializerMethodField()
    is_auction = serializers.BooleanField(read_only=True)
    seller = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'title', 'price', 'category', 'condition', 'status',
            'location', 'phone_number', 'is_auction',
            'auction_end_time', 'primary_image', 'owner_name', 'owner_id', 'seller', 'views_count', 'created_at'
        ]
        read_only_fields = ['id', 'owner_name', 'owner_id', 'views_count', 'created_at']
    
    def get_primary_image(self, obj):
        primary_img = obj.images.filter(is_primary=True).first()
        if primary_img:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary_img.image.url)
        return None

    def get_seller(self, obj):
        if not obj.owner:
            return None
            
        avatar_url = None
        is_verified = False
        
        try:
            profile = obj.owner.profile
            is_verified = profile.is_verified
            if profile.avatar:
                request = self.context.get('request')
                avatar_url = request.build_absolute_uri(profile.avatar.url) if request else profile.avatar.url
        except Exception:
            pass
            
        # Combine first and last name if available, else fallback to username
        full_name = f"{obj.owner.first_name} {obj.owner.last_name}".strip()
        name = full_name if full_name else obj.owner.username

        return {
            "id": obj.owner.id,
            "name": name,
            "avatar_url": avatar_url,
            "is_verified": is_verified
        }


class ProductDetailSerializer(serializers.ModelSerializer):
    """Detailed product serializer with all relations"""
    owner = UserSerializer(read_only=True)
    owner_profile = serializers.SerializerMethodField()
    images = ProductImageSerializer(many=True, read_only=True)
    auction = AuctionSerializer(read_only=True)
    seller = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'owner', 'owner_profile', 'seller', 'title', 'description', 
            'price', 'category', 'condition', 'status', 'location',
            'phone_number', 'is_auction', 'auction_end_time', 
            'views_count', 'images', 'auction', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'owner', 'views_count', 'created_at', 'updated_at']
    
    def get_owner_profile(self, obj):
        try:
            profile = obj.owner.profile
            return {
                'trust_score': profile.trust_score,
                'seller_rating': float(profile.seller_rating),
                'total_sales': profile.total_sales,
                'city': profile.city,
                'avatar': self.context['request'].build_absolute_uri(profile.avatar.url) if profile.avatar else None
            }
        except UserProfile.DoesNotExist:
            return None

    def get_seller(self, obj):
        if not obj.owner:
            return None
            
        avatar_url = None
        is_verified = False
        
        try:
            profile = obj.owner.profile
            is_verified = profile.is_verified
            if profile.avatar:
                request = self.context.get('request')
                avatar_url = request.build_absolute_uri(profile.avatar.url) if request else profile.avatar.url
        except Exception:
            pass
            
        full_name = f"{obj.owner.first_name} {obj.owner.last_name}".strip()
        name = full_name if full_name else obj.owner.username

        return {
            "id": obj.owner.id,
            "name": name,
            "avatar_url": avatar_url,
            "is_verified": is_verified
        }


# ──────────────────────────────────────────────────────────────
# AUTO-BIDDING ENGINE
# ──────────────────────────────────────────────────────────────

import threading
from django.db import connection

def run_auto_bidding_async(auction_id, detected_item):
    """Wrapper to run auto-bidding in a background thread to avoid UI lag."""
    from .models import Auction
    try:
        # Re-fetch auction in this thread's context
        auction = Auction.objects.get(id=auction_id)
        run_auto_bidding(auction, detected_item)
    except Exception as e:
        logger.error(f"[Agent] Async auto-bidding error: {e}")
    finally:
        connection.close()

def run_auto_bidding(auction, detected_item):
    """
    Agent discovery for auctions. Called after a new auction is created.
    
    Instead of placing bids automatically, this now:
    1. Finds matching active UserAgents for the detected_item.
    2. Evaluates each agent's requirements via LLM.
    3. Sends a 'bid_approval' notification with suggested bid amount.
    4. The user must approve the notification to place the actual bid.
    """
    from decimal import Decimal
    
    seller = auction.product.owner
    starting_bid = auction.starting_bid
    
    # Find matching active agents (exclude seller)
    potential_agents = list(
        UserAgent.objects.filter(
            target_item=detected_item,
            is_active=True,
            max_budget__gte=starting_bid
        ).exclude(user=seller)
         .select_related('user')
    )
    
    # Filter out agents already notified about this product
    already_notified_user_ids = set(
        Notification.objects.filter(
            related_product=auction.product,
            user__in=[a.user for a in potential_agents]
        ).values_list('user_id', flat=True)
    )
    potential_agents = [a for a in potential_agents if a.user_id not in already_notified_user_ids]
    
    if not potential_agents:
        return
    
    # --- LLM Evaluation Step ---
    from ai.agent_graph import smart_agent_evaluator
    product = auction.product
    
    for agent in potential_agents:
        if agent.requirements_prompt.strip():
            logger.info(f"[AgentGraph] Evaluating agent {agent.user.username} requirements...")
            eval_result = smart_agent_evaluator.invoke({
                "product_title": product.title,
                "product_desc": product.description,
                "product_condition": product.condition,
                "product_price": str(product.price),
                "agent_max_budget": str(agent.max_budget),
                "agent_requirements": agent.requirements_prompt,
            })
            
            reason = eval_result.get("reason", "") if isinstance(eval_result, dict) else getattr(eval_result, 'reason', '')
            is_match = eval_result.get("is_match", False) if isinstance(eval_result, dict) else getattr(eval_result, 'is_match', False)
            decision_type = eval_result.get("decision_type", "") if isinstance(eval_result, dict) else getattr(eval_result, 'decision_type', '')

            if is_match:
                logger.info(f"[AgentGraph] MATCH: {reason}")
                agent._ai_reasoning = reason
                _send_bid_approval_notification(agent, auction, starting_bid, detected_item)
            else:
                logger.info(f"[AgentGraph] REJECT ({decision_type}): {reason}")
                _notify_agent_rejection(agent, product, reason, decision_type)
        else:
            # No specific requirements, automatically match
            agent._ai_reasoning = f"المنتج طابق الفئة المطلوبة — السعر {product.price} جنيه في حدود ميزانيتك {agent.max_budget} جنيه ✅"
            _send_bid_approval_notification(agent, auction, starting_bid, detected_item)


def _send_bid_approval_notification(agent, auction, suggested_amount, detected_item):
    """Send a bid_approval notification asking the user to approve/reject bidding."""
    from ai.classifier import YOLO_CLASS_LABELS
    
    item_label = YOLO_CLASS_LABELS.get(detected_item, detected_item)
    product = auction.product
    reasoning = getattr(agent, '_ai_reasoning', '')
    
    title = f"🔔 الوكيل لقيلك منتج مناسب: {product.title[:60]}"
    message = (
        f"الوكيل الذكي بتاعك لقى \"{product.title}\" ({item_label}) "
        f"في مزاد بسعر بداية {auction.starting_bid} جنيه.\n"
        f"المبلغ المقترح للمزايدة: {suggested_amount} جنيه\n"
        f"ميزانيتك القصوى: {agent.max_budget} جنيه\n\n"
        f"عايز تزايد على المنتج ده؟"
    )
    
    if reasoning:
        message += f"\n\n📋 تحليل الوكيل: {reasoning}"
    
    Notification.objects.create(
        user=agent.user,
        title=title,
        message=message,
        related_product=product,
        related_auction=auction,
        reasoning=reasoning,
        notification_type='bid_approval',
        is_approved=None,
        suggested_bid=suggested_amount,
    )
    
    logger.info(f"[Agent] 📩 Sent bid approval request to {agent.user.username} for '{product.title}' (suggested: {suggested_amount})")

def _notify_agent_rejection(agent, product, reason, decision_type=''):
    """Notify the user that their agent matched the category but was rejected by LLM."""
    # Prevent duplicate rejection notifications for same user+product
    already_notified = Notification.objects.filter(
        user=agent.user,
        related_product=product,
        title__contains='تخطى منتج'
    ).exists()
    if already_notified:
        return
    
    # Build a user-friendly title based on decision type
    decision_icons = {
        'price_too_high': '💰',
        'wrong_brand': '🏷️',
        'wrong_type': '📦',
        'wrong_condition': '⚠️',
        'wrong_location': '📍',
        'missing_info': 'ℹ️',
        'partial_match': '🔶',
    }
    icon = decision_icons.get(decision_type, '🤖')
    
    title = f"{icon} الوكيل تخطى منتج: {product.title[:60]}"
    
    # Include the actual AI reason in the visible message
    message = (
        f"الوكيل لقى \"{product.title}\" (سعر: {product.price} جنيه) "
        f"من نفس الفئة المطلوبة لكن قرر ما يزايدش عليه.\n\n"
        f"📋 السبب: {reason}"
    )
    
    Notification.objects.create(
        user=agent.user,
        title=title,
        message=message,
        related_product=product,
        reasoning=reason
    )


def _notify_agent_insufficient_balance(agent, auction, amount):
    """Notify user that their agent couldn't bid due to insufficient wallet balance."""
    reasoning = getattr(agent, '_ai_reasoning', '')
    product = auction.product
    
    message = (
        f'الوكيل الذكي بتاعك لقى "{product.title}" وكان عايز يزايد بمبلغ {amount} جنيه '
        f'لكن رصيدك في المحفظة مش كفاية.\n'
        f'اشحن محفظتك عشان الوكيل يقدر يزايد.'
    )
    if reasoning:
        message += f'\n\n📋 تحليل المنتج: {reasoning}'
    
    Notification.objects.create(
        user=agent.user,
        title='⛔ الوكيل مقدرش يزايد - رصيد غير كافي',
        message=message,
        related_product=product,
        reasoning=reasoning,
    )


# Dynamic bid increment calculation
def _calc_bid_increment(current_bid):
    """5% of current bid, min 50 EGP, max 500 EGP."""
    from decimal import Decimal
    inc = max(Decimal('50.00'), min(Decimal(str(current_bid)) * Decimal('0.05'), Decimal('500.00')))
    return inc.quantize(Decimal('1.00'))


def agent_counter_bid_async(auction_id, manual_bidder_id):
    """Wrapper to run agent counter-bidding in a background thread."""
    from .models import Auction
    from django.contrib.auth.models import User
    try:
        auction = Auction.objects.get(id=auction_id)
        manual_bidder = User.objects.get(id=manual_bidder_id)
        agent_counter_bid(auction, manual_bidder)
    except Exception as e:
        logger.error(f"[Agent] Async counter-bid error: {e}")
    finally:
        connection.close()

def agent_counter_bid(auction, manual_bidder):
    """
    Called AFTER a manual bid is placed.
    Instead of auto-counter-bidding, sends bid_approval notifications
    to matching agents so the user can decide whether to counter-bid.
    """
    product = auction.product
    detected_item = product.detected_item

    if not detected_item:
        return

    # Find active agents for this item, excluding the manual bidder and the seller
    potential_agents = list(
        UserAgent.objects
        .filter(target_item=detected_item, is_active=True)
        .exclude(user=manual_bidder)
        .exclude(user=product.owner)
        .select_related('user')
    )

    if not potential_agents:
        return

    # Filter out agents that already have a pending approval notification for this auction
    already_notified_user_ids = set(
        Notification.objects.filter(
            related_auction=auction,
            notification_type='bid_approval',
            is_approved=None,  # Still pending
            user__in=[a.user for a in potential_agents]
        ).values_list('user_id', flat=True)
    )
    potential_agents = [a for a in potential_agents if a.user_id not in already_notified_user_ids]

    if not potential_agents:
        return

    # Calculate the counter-bid amount
    counter_amount = auction.current_bid + _calc_bid_increment(auction.current_bid)

    from ai.agent_graph import smart_agent_evaluator

    for agent in potential_agents:
        if counter_amount > agent.max_budget:
            logger.info(
                f"[Agent] ⛔ {agent.user.username}'s budget ({agent.max_budget}) "
                f"can't cover counter-bid ({counter_amount})"
            )
            continue

        # Check if agent already bid (proven match — skip LLM)
        already_bid = Bid.objects.filter(auction=auction, bidder=agent.user).exists()
        
        if already_bid:
            # Already proven match, send counter-bid approval directly
            agent._ai_reasoning = ''
            _send_bid_approval_notification(agent, auction, counter_amount, detected_item)
            continue

        # First time — run LLM evaluation
        if agent.requirements_prompt.strip():
            eval_result = smart_agent_evaluator.invoke({
                "product_title": product.title,
                "product_desc": product.description,
                "product_condition": product.condition,
                "product_price": str(product.price),
                "agent_max_budget": str(agent.max_budget),
                "agent_requirements": agent.requirements_prompt,
            })
            is_match = eval_result.get("is_match", False) if isinstance(eval_result, dict) else getattr(eval_result, 'is_match', False)
            reason = eval_result.get("reason", "") if isinstance(eval_result, dict) else getattr(eval_result, 'reason', '')
            decision_type = eval_result.get("decision_type", "") if isinstance(eval_result, dict) else getattr(eval_result, 'decision_type', '')
            
            if is_match:
                agent._ai_reasoning = reason
                _send_bid_approval_notification(agent, auction, counter_amount, detected_item)
            else:
                logger.info(f"[Agent] ❌ {agent.user.username} rejected by LLM ({decision_type}): {reason}")
                _notify_agent_rejection(agent, product, reason, decision_type)
        else:
            agent._ai_reasoning = f"المنتج طابق الفئة المطلوبة — السعر الحالي {auction.current_bid} جنيه في حدود ميزانيتك {agent.max_budget} جنيه ✅"
            _send_bid_approval_notification(agent, auction, counter_amount, detected_item)


# ──────────────────────────────────────────────────────────────


class ProductCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating products"""
    images = ProductImageSerializer(many=True, read_only=True)
    uploaded_images = serializers.ListField(
        child=serializers.ImageField(max_length=1000000, allow_empty_file=False),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = Product
        fields = [
            'id', 'title', 'description', 'price', 'category', 'condition', 
            'location', 'phone_number', 'is_auction',
            'auction_end_time', 'images', 'uploaded_images'
        ]
        read_only_fields = ['id']
    
    def create(self, validated_data):
        try:
            uploaded_images = validated_data.pop('uploaded_images', [])
            product = Product.objects.create(**validated_data)
            
            auction = None
            # Create Auction if is_auction and end_time provided
            # Auction starts NOW (at creation time)
            if product.is_auction and product.auction_end_time:
                auction = Auction.objects.create(
                    product=product,
                    starting_bid=product.price,
                    current_bid=product.price,
                    start_time=timezone.now(),
                    end_time=product.auction_end_time,
                    is_active=True
                )
            
            # Create product images
            for idx, image in enumerate(uploaded_images):
                ProductImage.objects.create(
                    product=product,
                    image=image,
                    is_primary=(idx == 0),
                    order=idx
                )
            
            # ── AI Agent Trigger ──────────────────────────────
            # Run YOLO classification and agent logic in a background thread
            # to prevent UI lag and gateway timeouts (especially when HF Space wakes from sleep).
            if uploaded_images:
                def run_ai_pipeline_bg(prod_id, auc_id):
                    try:
                        from marketplace.models import Product, Auction
                        from ai.classifier import classify_image, guess_item_from_text
                        
                        prod = Product.objects.get(id=prod_id)
                        auc = Auction.objects.get(id=auc_id) if auc_id else None
                        
                        first_image = prod.images.filter(is_primary=True).first()
                        if first_image and first_image.image:
                            try:
                                # Local storage uses path
                                image_path = first_image.image.path
                            except NotImplementedError:
                                # Cloud storage (Cloudinary) uses url
                                image_path = first_image.image.url
                                
                            result = classify_image(image_path)
                            detected_item = result.get('detected_class')
                            
                            # Fallback: if YOLO returns 'other' or fails, try to guess from title
                            if not detected_item or detected_item == 'other':
                                guessed = guess_item_from_text(prod.title)
                                if guessed:
                                    detected_item = guessed
                                    logger.info(f"[Agent] 💡 YOLO returned other/None. Guessed '{detected_item}' from title.")

                            if detected_item and detected_item != 'other':
                                # Store on Product for counter-bid lookup & agent discovery
                                prod.detected_item = detected_item
                                
                                # Always auto-correct category based on AI detection
                                # (even if user already chose a category, AI takes priority)
                                from ai.classifier import CATEGORY_MAP, ARABIC_TO_CATEGORY_ID
                                arabic_label = CATEGORY_MAP.get(detected_item)
                                if arabic_label:
                                    new_category_id = ARABIC_TO_CATEGORY_ID.get(arabic_label)
                                    if new_category_id and new_category_id != 'other':
                                        old_category = prod.category
                                        prod.category = new_category_id
                                        logger.info(f"[Agent] 🏷️ Category set to '{new_category_id}' (was '{old_category}') based on detected item '{detected_item}'")
                                
                                prod.save(update_fields=['detected_item', 'category'])
                                logger.info(f"[Agent] 🔍 Detected '{detected_item}' — checking agents...")
                                
                                if auc:
                                    logger.info(f"[Agent] 🚀 Running auto-bidding for '{detected_item}'...")
                                    from marketplace.serializers import run_auto_bidding
                                    run_auto_bidding(auc, detected_item)
                    except Exception as bg_err:
                        logger.error(f"[Agent/BG] AI pipeline background error: {bg_err}")
                        import traceback
                        traceback.print_exc()
                    finally:
                        from django.db import connection
                        connection.close()

                threading.Thread(
                    target=run_ai_pipeline_bg,
                    args=(product.id, auction.id if auction else None),
                    daemon=True
                ).start()
            # ──────────────────────────────────────────────────
            
            return product
        except Exception as e:
            if 'product' in locals():
                product.delete()
            # Log error for server-side debugging
            import traceback
            traceback.print_exc()
            # Return error to client
            raise serializers.ValidationError({"detail": f"Server Error: {str(e)}"})

    def to_representation(self, instance):
        try:
            return super().to_representation(instance)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "id": instance.id, 
                "title": instance.title, 
                "warning": "Product created but failed to serialize response",
                "error": str(e)
            }


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for user registration"""
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True, min_length=8)
    city = serializers.CharField(write_only=True)
    phone = serializers.CharField(
        write_only=True, 
        required=True, 
        error_messages={'required': 'رقم الهاتف مطلوب.', 'blank': 'رقم الهاتف مطلوب.'}
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2', 'first_name', 'last_name', 'city', 'phone']
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Passwords don't match"})
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password2')
        city = validated_data.pop('city')
        phone = validated_data.pop('phone', '')
        
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )
        
        # Use update_or_create because the post_save signal may have
        # already created a profile with empty defaults.
        UserProfile.objects.update_or_create(
            user=user,
            defaults={'city': city, 'phone': phone}
        )
        
        return user


class MessageSerializer(serializers.ModelSerializer):
    """Serializer for individual chat messages"""
    sender_name = serializers.CharField(source='sender.username', read_only=True)
    sender_avatar = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'sender_name', 'sender_avatar', 'content', 'is_read', 'created_at']
        read_only_fields = ['id', 'sender', 'created_at']

    def get_sender_avatar(self, obj):
        try:
            if obj.sender.profile.avatar:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(obj.sender.profile.avatar.url)
        except UserProfile.DoesNotExist:
            pass
        return None


class ConversationListSerializer(serializers.ModelSerializer):
    """Lightweight conversation serializer for list views"""
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_participant = serializers.SerializerMethodField()
    product_title = serializers.CharField(source='product.title', read_only=True)
    product_image = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'product', 'product_title', 'product_image',
            'other_participant', 'last_message', 'unread_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_last_message(self, obj):
        last_msg = obj.messages.order_by('-created_at').first()
        if last_msg:
            return {
                'content': last_msg.content[:100],
                'sender_name': last_msg.sender.username,
                'created_at': last_msg.created_at.isoformat(),
                'is_read': last_msg.is_read,
            }
        return None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.messages.filter(is_read=False).exclude(sender=request.user).count()
        return 0

    def get_other_participant(self, obj):
        request = self.context.get('request')
        if request and request.user:
            other_user = obj.seller if request.user == obj.buyer else obj.buyer
            avatar_url = None
            try:
                if other_user.profile.avatar:
                    avatar_url = request.build_absolute_uri(other_user.profile.avatar.url)
            except UserProfile.DoesNotExist:
                pass
            return {
                'id': other_user.id,
                'username': other_user.username,
                'avatar': avatar_url,
            }
        return None

    def get_product_image(self, obj):
        primary_img = obj.product.images.filter(is_primary=True).first()
        if primary_img:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary_img.image.url)
        return None


class ConversationDetailSerializer(serializers.ModelSerializer):
    """Full conversation serializer with all messages"""
    messages = MessageSerializer(many=True, read_only=True)
    buyer = UserSerializer(read_only=True)
    seller = UserSerializer(read_only=True)
    product_title = serializers.CharField(source='product.title', read_only=True)
    product_image = serializers.SerializerMethodField()
    other_participant = serializers.SerializerMethodField()


    class Meta:
        model = Conversation
        fields = [
            'id', 'product', 'product_title', 'product_image',
            'buyer', 'seller', 'other_participant', 'messages', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_other_participant(self, obj):
        request = self.context.get('request')
        if request and request.user:
            other_user = obj.seller if request.user == obj.buyer else obj.buyer
            # Handle case where user is neither buyer nor seller (e.g. admin)
            if not other_user:
                return None
                
            avatar_url = None
            try:
                if hasattr(other_user, 'profile') and other_user.profile.avatar:
                    avatar_url = request.build_absolute_uri(other_user.profile.avatar.url)
            except Exception:
                pass
            return {
                'id': other_user.id,
                'username': other_user.username,
                'avatar': avatar_url,
            }
        return None

    def get_product_image(self, obj):
        primary_img = obj.product.images.filter(is_primary=True).first()
        if primary_img:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary_img.image.url)
        return None


class UserAgentSerializer(serializers.ModelSerializer):
    """Serializer for AI Auto-Bidder agent configuration"""
    user_name = serializers.CharField(source='user.username', read_only=True)
    target_label = serializers.SerializerMethodField()

    class Meta:
        model = UserAgent
        fields = [
            'id', 'user', 'user_name', 'target_item', 'target_label',
            'max_budget', 'requirements_prompt', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'user_name', 'created_at', 'updated_at']

    def get_target_label(self, obj):
        """Return the human-readable Arabic label for the target item."""
        from ai.classifier import YOLO_CLASS_LABELS, CATEGORY_MAP
        item_label = YOLO_CLASS_LABELS.get(obj.target_item, obj.target_item)
        category_label = CATEGORY_MAP.get(obj.target_item, '')
        if category_label:
            return f"{item_label} ({category_label})"
        return item_label


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for user notifications"""
    product_title = serializers.CharField(source='related_product.title', read_only=True, allow_null=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'title', 'message', 'reasoning', 'is_read',
            'related_product', 'product_title', 'related_auction',
            'notification_type', 'is_approved', 'suggested_bid',
            'created_at'
        ]
        read_only_fields = [
            'id', 'title', 'message', 'reasoning',
            'related_product', 'related_auction',
            'notification_type', 'suggested_bid', 'created_at'
        ]


# ──────────────────────────────────────────────────────────────
# AGENT DISCOVERY ENGINE — Direct-Sale Product Matching
# ──────────────────────────────────────────────────────────────

def run_agent_discovery_async(product_id):
    """Agent discovery for non-auction products is DISABLED.
    The agent now only works for auctions."""
    logger.info(f"[AgentDiscovery] DISABLED — agent only works for auctions. Skipping product #{product_id}.")
    return


def run_agent_discovery(product):
    """DISABLED — The agent now only works for auctions.
    Non-auction products are ignored completely."""
    logger.info(f"[AgentDiscovery] DISABLED — agent only works for auctions. Skipping product #{product.id}.")
    return


class OrderSerializer(serializers.ModelSerializer):
    """Order serializer with buyer/seller role context."""
    product_title = serializers.CharField(source='product.title', read_only=True)
    role = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ['id', 'product_title', 'amount', 'role', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_role(self, obj):
        request = self.context.get('request')
        if request and request.user:
            if obj.buyer_id == request.user.id:
                return 'buyer'
            return 'seller'
        return None


class AgentPendingBidSerializer(serializers.ModelSerializer):
    """Serializer for AgentPendingBid — includes auction/product context for the UI."""

    auction_id = serializers.IntegerField(source='auction.id', read_only=True)
    product_title = serializers.CharField(source='auction.product.title', read_only=True)
    product_image = serializers.SerializerMethodField()
    current_bid = serializers.DecimalField(
        source='auction.current_bid', max_digits=10, decimal_places=2, read_only=True
    )
    auction_end_time = serializers.DateTimeField(source='auction.end_time', read_only=True)
    auction_is_active = serializers.BooleanField(source='auction.is_active', read_only=True)
    agent_id = serializers.IntegerField(source='agent.id', read_only=True)
    agent_target = serializers.CharField(source='agent.target_item', read_only=True)
    delta_amount = serializers.SerializerMethodField()

    class Meta:
        model = AgentPendingBid
        fields = [
            'id', 'agent_id', 'agent_target',
            'auction_id', 'product_title', 'product_image',
            'current_bid', 'auction_end_time', 'auction_is_active',
            'proposed_amount', 'previous_amount', 'delta_amount',
            'status', 'ai_reasoning', 'is_counter_bid', 'round_number',
            'created_at',
        ]
        read_only_fields = fields

    def get_product_image(self, obj):
        try:
            primary_img = obj.auction.product.images.filter(is_primary=True).first()
            if not primary_img:
                primary_img = obj.auction.product.images.first()
            if primary_img and primary_img.image:
                url = primary_img.image.url
                if url.startswith('http'):
                    return url
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(url)
                return url
        except Exception:
            pass
        return None

    def get_delta_amount(self, obj):
        """Amount the wallet will be charged on approval (proposed - previous)."""
        from decimal import Decimal
        delta = obj.proposed_amount - (obj.previous_amount or Decimal('0.00'))
        return str(max(delta, Decimal('0.00')))
