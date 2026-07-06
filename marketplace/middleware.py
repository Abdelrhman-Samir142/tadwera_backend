"""
JWT authentication middleware for Django Channels WebSocket connections.

Extracts JWT access token from the WebSocket query string (?token=xxx)
and authenticates the user using the existing SimpleJWT configuration.

Usage in ASGI routing:
    JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
"""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)


@database_sync_to_async
def get_user_from_token(token_str):
    """Validate a JWT access token and return the corresponding User."""
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from django.contrib.auth.models import User

        access_token = AccessToken(token_str)
        user_id = access_token["user_id"]
        return User.objects.get(id=user_id)
    except Exception as e:
        logger.debug(f"[WS Auth] Token validation failed: {e}")
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom middleware for Django Channels that authenticates WebSocket
    connections using JWT tokens passed via query string.

    Client connects with: ws://host/ws/chat/1/?token=<jwt_access_token>
    """

    async def __call__(self, scope, receive, send):
        # Extract token from query string
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)
        token_list = query_params.get("token", [])

        if token_list:
            scope["user"] = await get_user_from_token(token_list[0])
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)
