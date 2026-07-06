from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    ProductViewSet,
    AuctionViewSet,
    UserProfileViewSet,
    ConversationViewSet,
    UserAgentViewSet,
    OrderViewSet,
    register_view,
    current_user_view,
    get_general_stats,
    CustomTokenObtainPairView,
    wishlist_list,
    wishlist_toggle,
    wishlist_check,
    wishlist_ids,
    classify_image_view,
    get_agent_targets,
    notifications_list,
    notifications_mark_read,
    notifications_unread_count,
    notifications_delete_all,
    notification_respond,
    admin_products_list,
    admin_delete_product,
    admin_review_product,
    admin_users_list,
    admin_delete_user,
    admin_dashboard_stats_view,
    wallet_topup_view,
    wallet_transactions_view,
    verify_phone_request_view,
    reset_password_view,
    update_profile_view,
    change_password_view,
    visual_search_view,
    agent_pending_bids_list,
    agent_pending_bid_approve,
    agent_pending_bid_reject,
    get_categories,
    health_check,
)

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'auctions', AuctionViewSet, basename='auction')
router.register(r'profiles', UserProfileViewSet, basename='profile')
router.register(r'conversations', ConversationViewSet, basename='conversation')
router.register(r'agents', UserAgentViewSet, basename='agent')
router.register(r'orders', OrderViewSet, basename='order')

urlpatterns = [
    # Authentication endpoints
    path('auth/register/', register_view, name='register'),
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/me/', current_user_view, name='current_user'),
    path('auth/profile/update/', update_profile_view, name='update_profile'),
    path('auth/change-password/', change_password_view, name='change_password'),
    path('auth/verify-phone-request/', verify_phone_request_view, name='verify_phone_request'),
    path('auth/reset-password/', reset_password_view, name='reset_password'),
    path('general-stats/', get_general_stats, name='general-stats'),
    
    # Wishlist endpoints
    path('wishlist/', wishlist_list, name='wishlist-list'),
    path('wishlist/ids/', wishlist_ids, name='wishlist-ids'),
    path('wishlist/toggle/<int:product_id>/', wishlist_toggle, name='wishlist-toggle'),
    path('wishlist/check/<int:product_id>/', wishlist_check, name='wishlist-check'),
    
    # AI Classification
    path('classify-image/', classify_image_view, name='classify-image'),
    
    # AI Agent
    path('agent-targets/', get_agent_targets, name='agent-targets'),
    
    # Notifications
    path('notifications/', notifications_list, name='notifications-list'),
    path('notifications/mark-read/', notifications_mark_read, name='notifications-mark-read'),
    path('notifications/unread-count/', notifications_unread_count, name='notifications-unread-count'),
    path('notifications/delete-all/', notifications_delete_all, name='notifications-delete-all'),
    path('notifications/<int:notification_id>/respond/', notification_respond, name='notification-respond'),
    
    # Admin Dashboard API (IsAdminRole protected)
    path('admin-api/stats/', admin_dashboard_stats_view, name='admin-stats'),
    path('admin-api/products/', admin_products_list, name='admin-products'),
    path('admin-api/products/<int:product_id>/', admin_delete_product, name='admin-delete-product'),
    path('admin-api/products/<int:product_id>/review/', admin_review_product, name='admin-review-product'),
    path('admin-api/users/', admin_users_list, name='admin-users'),
    path('admin-api/users/<int:user_id>/', admin_delete_user, name='admin-delete-user'),
    
    # Wallet / Payment
    path('wallet/topup/', wallet_topup_view, name='wallet-topup'),
    path('wallet/transactions/', wallet_transactions_view, name='wallet-transactions'),
    
    # Visual Search
    path('visual-search/', visual_search_view, name='visual-search'),
    
    # Agent Pending Bids
    path('agent-pending-bids/', agent_pending_bids_list, name='agent-pending-bids-list'),
    path('agent-pending-bids/<int:pk>/approve/', agent_pending_bid_approve, name='agent-pending-bid-approve'),
    path('agent-pending-bids/<int:pk>/reject/', agent_pending_bid_reject, name='agent-pending-bid-reject'),
    
    # Categories
    path('categories/', get_categories, name='categories'),
    
    # Health check
    path('health/', health_check, name='health-check'),
    
    # Router URLs
    path('', include(router.urls)),
]


