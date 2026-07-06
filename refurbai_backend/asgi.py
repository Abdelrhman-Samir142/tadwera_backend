"""
ASGI config for refurbai_backend project.

Routes HTTP requests to Django and WebSocket connections
to Django Channels consumers with JWT authentication.
"""

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'refurbai_backend.settings')
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from marketplace.middleware import JWTAuthMiddleware
from marketplace.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    # HTTP requests → standard Django ASGI handler
    "http": get_asgi_application(),

    # WebSocket connections → JWT auth → URL router → consumers
    "websocket": JWTAuthMiddleware(
        URLRouter(websocket_urlpatterns)
    ),
})
