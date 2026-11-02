# myapp/middleware.py

import logging

from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

from .models import GameUser


logger = logging.getLogger("myapp.auth_middleware")


# ==========================================================
# PUBLIC PREFIXES — no auth required
#
# ✅ P0-7 FIX: /api/deposit/methods/ REMOVED
# (was leaking all payment account numbers to anyone)
# ==========================================================

PUBLIC_PREFIXES = [
    "/api/auth/send-otp/",
    "/api/auth/verify-email/",
    "/api/auth/check-username/",
    "/api/config/app/",
    "/api/gift/config/",
    "/admin/",
    "/management/",
    "/dashboard/",
    "/media/",
    "/static/",
]

# GET-only public endpoints (referral code share, leaderboard read)
PUBLIC_GET_PREFIXES = [
    "/api/leaderboard/",
    "/api/user/referral/",
]


# ==========================================================
# AUTH TOKEN MIDDLEWARE
# ==========================================================

class AuthTokenMiddleware(MiddlewareMixin):

    def process_request(self, request):

        path = request.path

        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return None

        if request.method == "GET":
            for prefix in PUBLIC_GET_PREFIXES:
                if path.startswith(prefix):
                    return None

        auth_token = request.headers.get("X-Auth-Token", "").strip()

        if not auth_token:
            return JsonResponse(
                {
                    "status": "error",
                    "code": "AUTH_REQUIRED",
                    "message": "Authentication required. Please log in.",
                },
                status=401,
            )

        user = GameUser.objects.filter(auth_token=auth_token).first()

        if not user:
            logger.warning(
                "INVALID AUTH | path=%s | token=%s...",
                path,
                auth_token[:12],
            )
            return JsonResponse(
                {
                    "status": "error",
                    "code": "AUTH_INVALID",
                    "message": "Session expired. Please log in again.",
                },
                status=401,
            )

        request.auth_user = user
        return None


# ==========================================================
# RATE LIMIT EXCEPTION HANDLER
# ==========================================================

class RateLimitResponseMiddleware(MiddlewareMixin):

    def process_exception(self, request, exception):

        try:
            from django_ratelimit.exceptions import Ratelimited
        except ImportError:
            return None

        if isinstance(exception, Ratelimited):
            logger.warning("RATE LIMITED | path=%s", request.path)
            return JsonResponse(
                {
                    "status": "error",
                    "code": "RATE_LIMITED",
                    "message": "Too many requests. Please wait and try again.",
                    "retry_after": 21600,
                },
                status=429,
            )

        return None


# ==========================================================
# CSP MIDDLEWARE (P2-12 prep — will be fully wired later)
# ==========================================================

class CSPMiddleware(MiddlewareMixin):
    """
    Adds a strict Content-Security-Policy header.
    Only applies to HTML responses (admin / management pages).
    JSON API responses skip this.
    """

    def process_response(self, request, response):
        content_type = response.get("Content-Type", "")
        if "text/html" in content_type:
            response["Content-Security-Policy"] = (
                "default-src 'self'; "
                "img-src 'self' data: https:; "
                "style-src 'self' 'unsafe-inline' https:; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
                "font-src 'self' https:; "
                "connect-src 'self' https: wss:; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )
            response["X-Content-Type-Options"] = "nosniff"
            response["X-Frame-Options"] = "DENY"
            response["Referrer-Policy"] = "same-origin"
        return response