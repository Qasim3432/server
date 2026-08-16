from django.urls import re_path

from .consumers import LudoGameConsumer


websocket_urlpatterns = [
    re_path(
        r"ws/ludo/(?P<game_id>\d+)/$",
        LudoGameConsumer.as_asgi(),
    ),
]