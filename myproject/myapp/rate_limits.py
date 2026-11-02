# myapp/rate_limits.py

from django_ratelimit.decorators import ratelimit


# ==========================================================
# Rate limit decorators
#
# Deposits / Withdrawals: NO rate limit here.
#   - Deposits: users can retry freely (admin manually approves)
#   - Withdrawals: PIN lockout (5 wrong → 12h) inside pin_management
#
# Each remaining decorator blocks when limit exceeded → 429
# via RateLimitResponseMiddleware
# ==========================================================


def otp_rate_limit(view_func):
    """10 OTP requests per minute per IP."""
    return ratelimit(
        key="ip",
        rate="10/m",
        method="POST",
        block=True,
    )(view_func)


def login_rate_limit(view_func):
    """20 login attempts per minute per IP."""
    return ratelimit(
        key="ip",
        rate="20/m",
        method="POST",
        block=True,
    )(view_func)


def spin_rate_limit(view_func):
    """20 spins per minute per device."""
    return ratelimit(
        key="post:device_token",
        rate="20/m",
        method="POST",
        block=True,
    )(view_func)


def join_wager_rate_limit(view_func):
    """20 game joins per minute per device."""
    return ratelimit(
        key="post:device_token",
        rate="20/m",
        method="POST",
        block=True,
    )(view_func)


# ==========================================================
# ✅ NEW — Balance / Config / Payment methods rate limits
# ==========================================================

def balance_rate_limit(view_func):
    """
    GET /api/deposit/balance/<token>/
    Prevents scraping — 60 req/min per device.
    """
    return ratelimit(
        key="ip",
        rate="60/m",
        method="GET",
        block=True,
    )(view_func)


def config_rate_limit(view_func):
    """
    GET /api/config/app/
    Public endpoint — prevent DDoS via cheap cache lookups.
    """
    return ratelimit(
        key="ip",
        rate="30/m",
        method="GET",
        block=True,
    )(view_func)


def payment_methods_rate_limit(view_func):
    """
    GET /api/deposit/methods/
    Auth required now — prevent enumeration.
    """
    return ratelimit(
        key="ip",
        rate="30/m",
        method="GET",
        block=True,
    )(view_func)