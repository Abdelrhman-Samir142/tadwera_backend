from django.core.exceptions import ValidationError
from django.db import models
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import (
    Auction,
    Bid,
    Message,
    Notification,
    Product,
    UserProfile,
    AgentPendingBid,
)
from .permissions import IsAdminRole, IsOwnerOrAdmin
from .serializers import (
    AgentPendingBidSerializer,
    AuctionSerializer,
    ConversationDetailSerializer,
    ConversationListSerializer,
    MessageSerializer,
    NotificationSerializer,
    ProductCreateSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    RegisterSerializer,
    UserAgentSerializer,
    UserProfileSerializer,
    UserSerializer,
)
from .services import (
    AIService,
    AIServiceError,
    AuctionBidError,
    AuctionService,
    ChatService,
    NotificationService,
    ProductService,
    ProductServiceError,
    StatsService,
    UserService,
    UserServiceError,
    VisualSearchError,
    VisualSearchService,
    WalletService,
    WishlistService,
)

close_expired_auctions = AuctionService.close_expired_auctions
send_winner_message = ChatService.send_winner_message


def _validation_error_message(exc):
    if getattr(exc, 'messages', None):
        return exc.messages[0]
    return str(exc)


def _service_error_response(exc):
    return Response(exc.payload, status=exc.status_code)


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        print(f"\n[Backend Auth] Login attempt received")
        print(f"[Backend Auth] Request data keys: {list(attrs.keys())}")

        login_input = attrs.get('username')
        password = attrs.get('password')
        if login_input and password and '@' in login_input:
            attrs['username'] = UserService.resolve_login_username(login_input)

        try:
            result = super().validate(attrs)
            result['is_admin'] = UserService.get_is_admin_flag(self.user)
            print(
                f"[Backend Auth] Login successful for user: {attrs.get('username')} "
                f"(is_admin={result['is_admin']})"
            )
            return result
        except Exception as e:
            print(f"[Backend Auth] Login failed: {str(e)}")
            raise


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def register_view(request):
    """User registration endpoint"""
    print(f"\n[Backend Auth] Registration attempt received")
    print(f"[Backend Auth] Request data: {request.data}")

    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        print(f"[Backend Auth] Registration failed with errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.save()
    print(f"[Backend Auth] Registration successful for user: {user.username}")
    refresh = RefreshToken.for_user(user)
    return Response({
        'user': UserSerializer(user).data,
        'tokens': {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        },
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user_view(request):
    """Get current authenticated user with profile"""
    profile = UserService.get_or_create_profile(request.user)
    data = UserProfileSerializer(profile, context={'request': request}).data
    data['is_admin'] = UserService.get_is_admin_flag(request.user)
    return Response(data)


class ProductViewSet(viewsets.ModelViewSet):
    """ViewSet for Product CRUD operations"""
    queryset = Product.objects.select_related('owner', 'owner__profile').prefetch_related(
        'images', 'auction', 'auction__bids__bidder__profile'
    )
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'condition', 'status', 'is_auction', 'owner']
    search_fields = ['title', 'description', 'location']
    ordering_fields = ['created_at', 'price', 'views_count']
    ordering = ['status', '-created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        if self.action in ('create', 'update', 'partial_update'):
            return ProductCreateSerializer
        return ProductDetailSerializer

    def get_queryset(self):
        return ProductService.get_visible_products_queryset(
            super().get_queryset(), self.request.user, self.action, self.request.query_params,
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        ProductService.increment_view_count(instance)
        return Response(self.get_serializer(instance).data)

    def perform_create(self, serializer):
        product = serializer.save(owner=self.request.user)
        ProductService.set_listing_defaults(product, self.request.user)
        product.save(update_fields=['status'])

    def perform_update(self, serializer):
        if self.request.user.is_staff or serializer.instance.owner == self.request.user:
            product = serializer.save()
            if not self.request.user.is_staff and product.owner == self.request.user:
                product.status = 'pending'
                product.save(update_fields=['status'])
            return
        raise PermissionDenied('You do not have permission to edit this product.')

    def perform_destroy(self, instance):
        if self.request.user.is_staff or instance.owner == self.request.user:
            instance.delete()
            return
        raise PermissionDenied('You do not have permission to delete this product.')

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_listings(self, request):
        products = ProductService.get_user_listings(self.queryset, request.user)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='buy', permission_classes=[IsAuthenticated])
    def buy(self, request, pk=None):
        try:
            order, product, price = ProductService.purchase_product(request.user, pk)
        except Product.DoesNotExist:
            return Response({'error': 'المنتج غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        except UserProfile.DoesNotExist:
            return Response({'error': 'الملف الشخصي غير موجود'}, status=status.HTTP_400_BAD_REQUEST)
        except ProductServiceError as e:
            return _service_error_response(e)

        ProductService.send_purchase_chat_message(request.user, product, price)
        return Response(
            ProductService.build_purchase_response(order, product),
            status=status.HTTP_201_CREATED,
        )


class AuctionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing auctions"""
    queryset = Auction.objects.select_related(
        'product', 'product__owner', 'highest_bidder',
    ).prefetch_related('bids__bidder__profile', 'product__images')
    serializer_class = AuctionSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return AuctionService.get_visible_auctions_queryset(
            super().get_queryset(), self.request.user, self.action, self.request.query_params,
        )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def place_bid(self, request, pk=None):
        try:
            amount = AuctionService.parse_bid_amount(request.data.get('amount', 0))
            AuctionService.ensure_bidder_profile(request.user)
            bid, auction = AuctionService.place_bid(request.user, pk, amount)
        except UserProfile.DoesNotExist:
            return Response({'error': 'الملف الشخصي غير موجود'}, status=status.HTTP_400_BAD_REQUEST)
        except Auction.DoesNotExist:
            return Response({'error': 'المزاد غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        except AuctionBidError as e:
            return _service_error_response(e)
        except Exception as e:
            AuctionService.log_place_bid_crash(pk, e)
            return Response(
                {'error': 'حدث خطأ أثناء تنفيذ المزايدة. الرجاء المحاولة مرة أخرى.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        AuctionService.run_agent_counter_bid(auction, request.user)
        return Response(AuctionService.build_place_bid_response(bid), status=status.HTTP_201_CREATED)


class UserProfileViewSet(viewsets.ModelViewSet):
    """ViewSet for user profiles"""
    queryset = UserProfile.objects.select_related('user')
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return UserService.get_scoped_profile_queryset(
            self.queryset, self.request.user, self.action,
        )

    @action(detail=False, methods=['get', 'patch', 'put'], permission_classes=[IsAuthenticated])
    def me(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        if request.method in ['PATCH', 'PUT']:
            serializer = self.get_serializer(profile, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return Response(self.get_serializer(profile).data)

    @action(detail=False, methods=['get'], url_path=r'by_user/(?P<user_id>\d+)', permission_classes=[AllowAny])
    def by_user(self, request, user_id=None):
        return Response(UserService.get_public_profile(user_id, request))

    @action(detail=False, methods=['post'], url_path=r'rate/(?P<user_id>\d+)', permission_classes=[IsAuthenticated])
    def rate(self, request, user_id=None):
        try:
            result = UserService.rate_seller(request.user, user_id, request.data.get('rating'))
        except ValidationError as e:
            return Response({'error': _validation_error_message(e)}, status=status.HTTP_400_BAD_REQUEST)
        except UserServiceError as e:
            return _service_error_response(e)
        return Response(result)


class ConversationViewSet(viewsets.ModelViewSet):
    """ViewSet for chat conversations"""
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return ConversationListSerializer if self.action == 'list' else ConversationDetailSerializer

    def get_queryset(self):
        return ChatService.get_user_conversations_queryset(self.request.user)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        ChatService.mark_conversation_read(instance, request.user)
        return Response(self.get_serializer(instance).data)

    @action(detail=False, methods=['post'])
    def start_conversation(self, request):
        product_id = request.data.get('product_id')
        if not product_id:
            return Response({'error': 'product_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            conversation, created = ChatService.start_or_get_conversation(request.user, product_id)
        except Product.DoesNotExist:
            raise Http404
        except ValidationError as e:
            return Response({'error': _validation_error_message(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ConversationDetailSerializer(conversation, context={'request': request})
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(serializer.data, status=code)

    @action(detail=True, methods=['post'])
    def send_message(self, request, pk=None):
        content = request.data.get('content', '').strip()
        if not content:
            return Response({'error': 'Message content is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            message = ChatService.send_message(self.get_object(), request.user, content)
        except PermissionDenied as e:
            return Response({'error': e.detail}, status=status.HTTP_403_FORBIDDEN)
        serializer = MessageSerializer(message, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        return Response({'unread_count': ChatService.get_unread_count(request.user)})

    @action(detail=True, methods=['delete'])
    def delete_conversation(self, request, pk=None):
        try:
            ChatService.delete_conversation(self.get_object(), request.user)
        except PermissionDenied as e:
            return Response({'error': e.detail}, status=status.HTTP_403_FORBIDDEN)
        return Response({'status': 'deleted'}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['delete'], url_path='delete_message/(?P<message_id>[0-9]+)')
    def delete_message(self, request, pk=None, message_id=None):
        message = get_object_or_404(Message, id=message_id, conversation=self.get_object())
        try:
            ChatService.delete_message(message, request.user)
        except PermissionDenied as e:
            return Response({'error': e.detail}, status=status.HTTP_403_FORBIDDEN)
        return Response({'status': 'deleted'}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['patch'], url_path='edit_message/(?P<message_id>[0-9]+)')
    def edit_message(self, request, pk=None, message_id=None):
        content = request.data.get('content', '').strip()
        if not content:
            return Response({'error': 'Message content is required'}, status=status.HTTP_400_BAD_REQUEST)
        message = get_object_or_404(Message, id=message_id, conversation=self.get_object())
        try:
            message = ChatService.edit_message(message, request.user, content)
        except PermissionDenied as e:
            return Response({'error': e.detail}, status=status.HTTP_403_FORBIDDEN)
        return Response(MessageSerializer(message, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([AllowAny])
@cache_page(60 * 15)
def get_general_stats(request):
    return Response(StatsService.get_landing_page_stats())


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wishlist_list(request):
    return Response(WishlistService.list_wishlist_products(request.user, request))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def wishlist_toggle(request, product_id):
    try:
        data, response_status = WishlistService.toggle_wishlist(request.user, product_id)
    except Product.DoesNotExist:
        return Response({'error': 'المنتج غير موجود'}, status=status.HTTP_404_NOT_FOUND)
    return Response(data, status=response_status)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wishlist_check(request, product_id):
    return Response({'is_wishlisted': WishlistService.is_wishlisted(request.user, product_id)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wishlist_ids(request):
    return Response({'product_ids': WishlistService.get_wishlisted_product_ids(request.user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def classify_image_view(request):
    image_file = request.FILES.get('image')
    if not image_file:
        return Response({'error': 'No image file provided'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response(AIService.classify_uploaded_image(image_file))
    except AIServiceError as e:
        return _service_error_response(e)


class UserAgentViewSet(viewsets.ModelViewSet):
    """CRUD ViewSet for AI Auto-Bidder agents"""
    serializer_class = UserAgentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserService.get_user_agents_queryset(self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_agent_targets(request):
    return Response(AIService.get_agent_target_list())


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notifications_list(request):
    notifications = NotificationService.list_for_user(request.user)
    return Response(NotificationSerializer(notifications, many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notifications_mark_read(request):
    NotificationService.mark_all_read(request.user)
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notifications_unread_count(request):
    return Response({'unread_count': NotificationService.unread_count(request.user)})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def notifications_delete_all(request):
    NotificationService.delete_all(request.user)
    return Response({'status': 'ok'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_respond(request, notification_id):
    notif = get_object_or_404(Notification, id=notification_id, user=request.user)
    payload, code = NotificationService.respond_to_bid_approval(
        request.user, notif, request.data.get('action'),
    )
    return Response(payload, status=code)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def admin_review_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    try:
        _, status_key = ProductService.review_product(
            product, request.data.get('action'), request.data.get('reason', 'مخالف لشروط النشر'),
        )
    except ProductServiceError as e:
        return _service_error_response(e)
    return Response({'status': status_key})


@api_view(['GET'])
@permission_classes([IsAdminRole])
def admin_products_list(request):
    return ProductService.get_admin_products_list(request)


@api_view(['DELETE'])
@permission_classes([IsAdminRole])
def admin_delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    title = ProductService.delete_product(product)
    return Response({'status': 'deleted', 'title': title}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def admin_users_list(request):
    return UserService.get_admin_users_list(request)


@api_view(['DELETE'])
@permission_classes([IsAdminRole])
def admin_delete_user(request, user_id):
    try:
        username = UserService.delete_user(request.user, user_id)
    except UserServiceError as e:
        return _service_error_response(e)
    return Response({'status': 'deleted', 'username': username}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def wallet_topup_view(request):
    try:
        amount = WalletService.validate_topup_amount(request.data.get('amount'))
    except ValidationError as e:
        return Response({'error': _validation_error_message(e)}, status=status.HTTP_400_BAD_REQUEST)
    try:
        new_balance = WalletService.topup(request.user, amount)
    except UserProfile.DoesNotExist:
        return Response({'error': 'الملف الشخصي غير موجود'}, status=status.HTTP_404_NOT_FOUND)
    return Response(WalletService.build_topup_response(new_balance, amount))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wallet_transactions_view(request):
    return Response(WalletService.get_transaction_history(request.user))


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_phone_request_view(request):
    email = request.data.get('email', '').strip()
    if not email:
        return Response({'error': 'البريد الإلكتروني مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response({'masked_numbers': UserService.generate_phone_decoys(email)})
    except UserServiceError as e:
        return _service_error_response(e)


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_view(request):
    email = request.data.get('email', '').strip()
    selected_masked = request.data.get('selected_masked_number', '').strip()
    full_phone = request.data.get('full_phone_number_input', '').strip()
    new_password = request.data.get('new_password', '').strip()
    if not all([email, selected_masked, full_phone, new_password]):
        return Response({'error': 'جميع الحقول مطلوبة'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        UserService.reset_password_with_phone(email, selected_masked, full_phone, new_password)
    except UserServiceError as e:
        return _service_error_response(e)
    return Response({'message': 'تم تغيير كلمة المرور بنجاح'})


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_profile_view(request):
    try:
        return Response(UserService.update_profile_fields(request.user, request.data))
    except UserServiceError as e:
        return _service_error_response(e)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    try:
        UserService.change_password(
            request.user,
            request.data.get('old_password', ''),
            request.data.get('new_password', ''),
            request.data.get('confirm_new_password', ''),
        )
    except UserServiceError as e:
        return _service_error_response(e)
    return Response({'message': 'تم تغيير كلمة المرور بنجاح. لطفا قم بتسجيل الدخول مرة أخرى إذا لزم الأمر.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def visual_search_view(request):
    image_file = request.FILES.get('image')
    if not image_file:
        return Response({'error': 'يجب رفع صورة للبحث'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response(VisualSearchService.search_similar_products(image_file, request))
    except VisualSearchError as e:
        return _service_error_response(e)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response(
            {'error': f'حدث خطأ أثناء البحث البصري: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/orders/ — buyer and seller order history"""
    from .serializers import OrderSerializer

    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer

    def get_queryset(self):
        return ProductService.get_orders_queryset(self.request.user)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx


@api_view(['GET'])
@permission_classes([IsAdminRole])
def admin_dashboard_stats_view(request):
    from datetime import timedelta
    from django.contrib.auth.models import User
    from django.utils import timezone
    
    now = timezone.now()
    one_week_ago = now - timedelta(days=7)
    
    total_users = User.objects.count()
    new_users_week = User.objects.filter(date_joined__gte=one_week_ago).count()
    
    active_products = Product.objects.filter(status='active').count()
    total_products = Product.objects.count()
    pending_products = Product.objects.filter(status='pending').count()
    sold_products = Product.objects.filter(status='sold').count()
    
    total_auctions = Auction.objects.count()
    active_auctions = Auction.objects.filter(is_active=True).count()
    
    recent_products_list = []
    for p in Product.objects.select_related('owner').order_by('-created_at')[:5]:
        recent_products_list.append({
            'id': p.id,
            'title': p.title,
            'price': float(p.price) if p.price else 0.0,
            'status': p.status,
            'owner_name': p.owner.username,
            'created_at': p.created_at.isoformat(),
        })
        
    recent_users_list = []
    for u in User.objects.order_by('-date_joined')[:5]:
        recent_users_list.append({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'date_joined': u.date_joined.isoformat(),
            'is_staff': u.is_staff,
            'is_active': u.is_active,
        })
        
    return Response({
        'total_users': total_users,
        'new_users_week': new_users_week,
        'active_products': active_products,
        'total_products': total_products,
        'pending_products': pending_products,
        'sold_products': sold_products,
        'total_auctions': total_auctions,
        'active_auctions': active_auctions,
        'recent_products': recent_products_list,
        'recent_users': recent_users_list,
    })


# ──────────────────────────────────────────────────────────────
# AGENT PENDING BIDS ENDPOINTS
# ──────────────────────────────────────────────────────────────

import logging
_logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agent_pending_bids_list(request):
    """
    GET /api/agent-pending-bids/
    Return all pending (status='pending') AI proposed bids for the current user.
    """
    pending = AgentPendingBid.objects.filter(
        agent__user=request.user,
        status='pending',
    ).select_related(
        'agent', 'auction', 'auction__product', 'notification'
    ).prefetch_related('auction__product__images').order_by('-created_at')

    serializer = AgentPendingBidSerializer(pending, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def agent_pending_bid_approve(request, pk):
    """
    POST /api/agent-pending-bids/{id}/approve/
    Approve a pending bid:
    - Validates auction is still active.
    - Validates proposed_amount > current_bid.
    - Deducts delta (proposed_amount - previous_amount) from wallet.
    - Creates Bid, updates Auction, refunds previous highest bidder.
    - Marks pending bid as 'approved'.
    """
    from django.db import transaction
    from decimal import Decimal
    from django.utils import timezone

    try:
        pending_bid = AgentPendingBid.objects.select_related(
            'agent', 'agent__user', 'agent__user__profile',
            'auction', 'auction__product', 'auction__highest_bidder',
        ).get(pk=pk, agent__user=request.user, status='pending')
    except AgentPendingBid.DoesNotExist:
        return Response(
            {'error': 'المزايدة المعلقة غير موجودة أو تمت معالجتها مسبقاً'},
            status=status.HTTP_404_NOT_FOUND
        )

    with transaction.atomic():
        # Lock the auction row
        auction = Auction.objects.select_for_update().get(pk=pending_bid.auction_id)

        # Validate auction is still active
        if not auction.is_active:
            return Response({'error': 'المزاد غير نشط'}, status=status.HTTP_400_BAD_REQUEST)
        if auction.end_time < timezone.now():
            auction.is_active = False
            auction.save(update_fields=['is_active'])
            return Response({'error': 'انتهى وقت المزاد'}, status=status.HTTP_400_BAD_REQUEST)

        proposed_amount = pending_bid.proposed_amount
        previous_amount = pending_bid.previous_amount or Decimal('0.00')

        # Validate proposed_amount is still competitive
        if proposed_amount < auction.current_bid or (
            proposed_amount == auction.current_bid and auction.highest_bidder is not None
        ):
            pending_bid.status = 'expired'
            pending_bid.save(update_fields=['status'])
            return Response(
                {'error': f'المبلغ المقترح ({proposed_amount}) لم يعد صالحاً لأن المزايدة الحالية ({auction.current_bid}). تم إلغاء الطلب.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        delta = proposed_amount - previous_amount
        if delta < Decimal('0.00'):
            delta = Decimal('0.00')

        # Check wallet
        agent_profile = pending_bid.agent.user.profile
        if agent_profile.wallet_balance < delta:
            return Response(
                {'error': f'رصيد المحفظة غير كافٍ. المطلوب: {delta} ج.م، المتاح: {agent_profile.wallet_balance} ج.م'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Refund previous highest bidder (if exists and is not the agent)
        previous_highest_bidder = auction.highest_bidder
        if previous_highest_bidder and previous_highest_bidder != pending_bid.agent.user:
            highest_bid_obj = Bid.objects.filter(
                auction=auction, bidder=previous_highest_bidder
            ).order_by('-amount').first()
            if highest_bid_obj:
                prev_profile = previous_highest_bidder.profile
                prev_profile.wallet_balance += highest_bid_obj.amount
                prev_profile.save(update_fields=['wallet_balance'])
                _logger.info(
                    f"[PendingBid] Refunded {previous_highest_bidder.username} "
                    f"amount {highest_bid_obj.amount}"
                )

        # Deduct delta from wallet
        agent_profile.wallet_balance -= delta
        agent_profile.save(update_fields=['wallet_balance'])

        # Create the actual Bid
        bid = Bid.objects.create(
            auction=auction,
            bidder=pending_bid.agent.user,
            amount=proposed_amount,
        )

        # Update auction
        auction.current_bid = proposed_amount
        auction.highest_bidder = pending_bid.agent.user
        auction.save(update_fields=['current_bid', 'highest_bidder'])

        # Mark pending bid as approved
        pending_bid.status = 'approved'
        pending_bid.save(update_fields=['status'])

        # Success notification
        Notification.objects.create(
            user=pending_bid.agent.user,
            title='✅ تمت المزايدة بنجاح!',
            message=(
                f'تمت الموافقة على مزايدة الوكيل بمبلغ {proposed_amount} ج.م '
                f'على "{auction.product.title}". '
                f'تم خصم {delta} ج.م من محفظتك.'
            ),
            related_product=auction.product,
        )

        _logger.info(
            f"[PendingBid] ✅ Approved bid {pending_bid.id} — "
            f"{pending_bid.agent.user.username} bid {proposed_amount} (delta {delta})"
        )

    return Response(
        {'status': 'approved', 'bid_id': bid.id, 'amount': str(proposed_amount), 'delta': str(delta)},
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def agent_pending_bid_reject(request, pk):
    """
    POST /api/agent-pending-bids/{id}/reject/
    Reject a pending bid — marks it as 'rejected', no wallet changes.
    """
    try:
        pending_bid = AgentPendingBid.objects.get(
            pk=pk, agent__user=request.user, status='pending'
        )
    except AgentPendingBid.DoesNotExist:
        return Response(
            {'error': 'المزايدة المعلقة غير موجودة أو تمت معالجتها مسبقاً'},
            status=status.HTTP_404_NOT_FOUND
        )

    pending_bid.status = 'rejected'
    pending_bid.save(update_fields=['status'])
    _logger.info(f"[PendingBid] ❌ Rejected pending bid {pending_bid.id}")
    return Response({'status': 'rejected'}, status=status.HTTP_200_OK)


# ──────────────────────────────────────────────────────────────
# CATEGORIES ENDPOINT
# ──────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def get_categories(request):
    """
    GET /api/categories/
    Return all available product categories based on Product model choices.
    """
    categories = [
        {'id': choice[0], 'name': choice[1]}
        for choice in Product.CATEGORY_CHOICES
    ]
    return Response(categories)


# ──────────────────────────────────────────────────────────────
# HEALTH CHECK ENDPOINT
# ──────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    GET /api/health/
    Returns system health for load balancers and monitoring.
    No authentication required.
    """
    from django.db import connection
    import time

    health = {
        'status': 'ok',
        'version': '1.0.0',
        'database': 'unknown',
    }

    # Check database connectivity
    try:
        start = time.time()
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_latency_ms = int((time.time() - start) * 1000)
        health['database'] = 'ok'
        health['db_latency_ms'] = db_latency_ms
    except Exception as e:
        health['status'] = 'degraded'
        health['database'] = f'error: {str(e)}'

    http_status = 200 if health['status'] == 'ok' else 503
    return Response(health, status=http_status)
