# myproject/asgi.py
import os
from django.core.asgi import get_asgi_application

# 1. Initialize os environment BEFORE importing consumers or routing!
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django_asgi_app = get_asgi_application()

# 2. Now import Channels components safely
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import myapp.routing

# 3. This structure separates HTTP from WebSocket traffic cleanly
application = ProtocolTypeRouter({
    # Handles standard web pages and restful HTTP traffic
    "http": django_asgi_app,
    
    # Handles real-time Android gameplay frames
    "websocket": AuthMiddlewareStack(
        URLRouter(
            myapp.routing.websocket_urlpatterns
        )
    ),
})