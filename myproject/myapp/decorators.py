# myapp/decorators.py
#
# ✅ NEW: Device ownership check helpers
#
# Problem:
#   AuthTokenMiddleware sirf ye verify karta hai ke X-Auth-Token kisi
#   valid user ka hai. LEKIN ye check nahi karta ke URL/body me jo
#   device_token hai woh usi authenticated user ka hai.
#
#   Result: koi bhi logged-in user kisi bhi doosre user ka transaction
#   history, game history, spin history, referral dashboard, withdrawal
#   status fetch kar sakta tha — sirf device_token pata hona kaafi tha.
#
# Fix:
#   URL-based views → @require_device_owner decorator
#   Body/query-based views → require_player_token_owner() inline check

import logging
from functools import wraps

from django.http import JsonResponse


logger = logging.getLogger("myapp.decorators")


def _forbidden_response():
    return JsonResponse(
        {
            "status": "error",
            "code": "FORBIDDEN",
            "message": "You are not allowed to access this resource.",
        },
        status=403,
    )


def require_device_owner(view_func):
    """
    Verify that X-Auth-Token owner matches the device_token
    present in the URL kwargs.

    Usage:
        @require_device_owner
        def get_game_history(request, device_token):
            ...
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        auth_user = getattr(request, "auth_user", None)
        url_token = kwargs.get("device_token")

        if not auth_user:
            logger.warning(
                "AUTHZ FAIL (no auth_user) | path=%s",
                request.path,
            )
            return JsonResponse(
                {
                    "status": "error",
                    "code": "AUTH_REQUIRED",
                    "message": "Authentication required.",
                },
                status=401,
            )

        if not url_token:
            logger.warning(
                "AUTHZ FAIL (no device_token in URL) | path=%s",
                request.path,
            )
            return _forbidden_response()

        if auth_user.device_id != url_token:
            logger.warning(
                "AUTHZ FAIL (device mismatch) | path=%s | auth=%s | url=%s",
                request.path,
                (auth_user.device_id or "")[:24],
                url_token[:24],
            )
            return _forbidden_response()

        return view_func(request, *args, **kwargs)

    return wrapper


def require_player_token_owner(request, player_token):
    """
    For views that take device_token/player_token via POST body
    or query string (not URL kwarg).

    Returns None if authorized, or JsonResponse if not.

    Usage:
        denied = require_player_token_owner(request, player_token)
        if denied:
            return denied
    """

    auth_user = getattr(request, "auth_user", None)

    if not auth_user:
        return JsonResponse(
            {
                "status": "error",
                "code": "AUTH_REQUIRED",
                "message": "Authentication required.",
            },
            status=401,
        )

    if not player_token or auth_user.device_id != player_token:
        logger.warning(
            "AUTHZ FAIL (body token mismatch) | path=%s | auth=%s | body=%s",
            request.path,
            (auth_user.device_id or "?")[:24],
            (player_token or "?")[:24],
        )
        return _forbidden_response()

    return None