# myapp/views/wallet.py

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q
from django.db import IntegrityError
from django.core.cache import cache
import json
import logging

from ..models import (
    SystemPaymentMethod,
    SystemTransactionLog,
    UserProfileBalance,
    SystemConfiguration,
    SystemSetting,
    ExchangeRate,           # ✅ P0-2: needed for rates
)
from ..currency_utils import format_dollar
from ..decorators import require_device_owner, require_player_token_owner
from ..request_utils import get_client_ip
from ..rate_limits import balance_rate_limit, config_rate_limit


logger = logging.getLogger("myapp.wallet")


# ==========================================================
# APP CONFIG (public but cached + rate limited)
#
# ✅ P0-2 FIX: ExchangeRate model se rates fetch
# ✅ P1-3 FIX: 60s cache + rate limit
# ==========================================================

@csrf_exempt
@config_rate_limit
def get_app_config(request):
    # ✅ P1-3: 60 sec cache
    cached = cache.get("app_config_payload")
    if cached is not None:
        return JsonResponse(cached)

    try:
        config = SystemConfiguration.get_solo()

        # ✅ P0-2 FIX: Rates from ExchangeRate (not SystemConfiguration)
        pk_rate_obj = ExchangeRate.objects.filter(country="PK").first()
        in_rate_obj = ExchangeRate.objects.filter(country="IN").first()

        usd_to_pkr = float(pk_rate_obj.usd_to_local_rate) if pk_rate_obj else 280.00
        usd_to_inr = float(in_rate_obj.usd_to_local_rate) if in_rate_obj else 84.00

        def _int_setting(key, default):
            try:
                return int(SystemSetting.get_value(key, str(default)))
            except (ValueError, TypeError):
                return default

        def _str_setting(key, default=""):
            return SystemSetting.get_value(key, default)

        payload = {
            "status": "success",

            # ✅ FIXED: These were crashing with AttributeError
            "usd_to_inr_rate": usd_to_inr,
            "usd_to_pkr_rate": usd_to_pkr,
            "usdt_wallet_address": config.usdt_wallet_address or "",

            "supported_currencies": ["INR", "PKR", "USDT", "USD"],

            "platform_tax_percentage": int(config.platform_tax_percentage),
            "winner_payout_percentage": int(config.winner_payout_percentage),
            "withdrawal_commission_percentage": int(
                config.withdrawal_commission_percentage
            ),

            "deposit_bonus_coins": _int_setting("deposit_bonus_coins", 100),
            "gift_enabled": SystemSetting.get_value("gift_enabled", "1") == "1",
            "paid_spin_cost": _int_setting("paid_spin_cost", 40),

            "supported_countries": ["PK", "IN"],

            "support_whatsapp": _str_setting("support_whatsapp", "+923001234567"),
            "support_telegram": _str_setting("support_telegram", "yourusername"),
            "support_email": _str_setting("support_email", "bedrockentertainent@gmail.com"),
            "terms_text": _str_setting(
                "terms_text",
                (
                    "1. App ka misuse mat karo\n"
                    "2. Apna account kisi ko share mat karo\n"
                    "3. Hamara data copy karna mana hai\n"
                    "4. Support se tameez se baat karo\n"
                    "5. Rules torney pe account block ho sakta hai"
                ),
            ),
            "privacy_text": _str_setting(
                "privacy_text",
                (
                    "Hum tumhara data securely store karte hain. "
                    "Kisi third party ko share nahi karte. "
                    "Account delete karna ho to support se rabta karo."
                ),
            ),
            "app_version": _str_setting("app_version", "1.0.0"),
            "referral_share_text": _str_setting(
                "referral_share_text",
                (
                    "Join me on Rocks Games! 🎮\n\n"
                    "Use my referral code: {code}\n"
                    "We both get 50 coins! 🎁"
                ),
            ),
        }

        # ✅ Cache for 60 seconds
        cache.set("app_config_payload", payload, timeout=60)
        return JsonResponse(payload)

    except Exception:
        logger.exception("get_app_config failed")
        return JsonResponse(
            {"status": "error", "message": "Config unavailable."},
            status=500,
        )


# ==========================================================
# TRANSACTION HISTORY (auth)
# ==========================================================

@require_device_owner
def get_transaction_history(request, device_token):
    profile = UserProfileBalance.objects.filter(
        device_token=device_token
    ).first()

    if not profile:
        return JsonResponse(
            {"status": "success", "transactions": [], "has_more": False}
        )

    try:
        limit = int(request.GET.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    try:
        offset = int(request.GET.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    qs = SystemTransactionLog.objects.filter(
        user_profile=profile
    ).order_by("-timestamp")
    total = qs.count()
    logs = qs[offset : offset + limit]

    transactions = [
        {
            "type": log.log_type,
            "amount": log.amount,
            "amount_display": format_dollar(log.amount),
            "status": "SUCCESS",
            "date": log.timestamp.strftime("%d %b %Y, %I:%M %p"),
            "reference": log.reference_id or "",
        }
        for log in logs
    ]

    return JsonResponse({
        "status": "success",
        "transactions": transactions,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(transactions) < total,
    })


# ==========================================================
# PAYMENT DETAILS — REGION FILTERED
#
# ✅ P0-7 FIX: authz (was public, leaked account numbers)
# ==========================================================

@csrf_exempt
def get_active_payment_details(request):

    device_token = str(request.GET.get("device_token", "")).strip()

    # ✅ P0-7 AUTHZ: X-Auth-Token owner must match device_token
    denied = require_player_token_owner(request, device_token)
    if denied:
        return denied

    user_country = "PK"

    profile = UserProfileBalance.objects.filter(
        device_token=device_token
    ).first()
    if profile and profile.country:
        user_country = profile.country

    methods = SystemPaymentMethod.objects.filter(
        is_active=True,
    ).filter(
        Q(country=user_country) | Q(country="ALL")
    )

    data = {
        m.method_type: {
            "name": m.account_name,
            "number": m.account_number,
            "country": m.country,
        }
        for m in methods
    }

    return JsonResponse({
        "status": "success",
        "country": user_country,
        "methods": data,
    })


# ==========================================================
# USER BALANCE
#
# ✅ P1-2 FIX: rate limit
# ✅ P1-4 FIX: race condition in get_or_create
# ==========================================================

@require_device_owner
@balance_rate_limit
def get_user_balance(request, device_token):

    # ✅ P1-4 FIX: catch IntegrityError on concurrent get_or_create
    try:
        profile, _ = UserProfileBalance.objects.get_or_create(
            device_token=device_token
        )
    except IntegrityError:
        profile = UserProfileBalance.objects.filter(
            device_token=device_token
        ).first()
        if not profile:
            return JsonResponse(
                {"status": "error", "message": "Profile unavailable."},
                status=503,
            )

    client_ip = get_client_ip(request)
    if client_ip and client_ip != "unknown" and profile.ip_address != client_ip:
        profile.ip_address = client_ip
        profile.save(update_fields=["ip_address"])

    return JsonResponse({
        "status": "success",
        "coins": profile.coins,
        "coins_display": format_dollar(profile.coins),
        "locked_coins": profile.locked_coins,
        "locked_coins_display": format_dollar(profile.locked_coins),
        "currency": profile.currency,
        "country": profile.country or "",
    })


# ==========================================================
# USER LOCATION
# ==========================================================

@csrf_exempt
def update_user_location(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        latitude = data.get("latitude")
        longitude = data.get("longitude")

        if not device_token or latitude is None or longitude is None:
            return JsonResponse({"error": "Missing fields"}, status=400)

        denied = require_player_token_owner(request, device_token)
        if denied:
            return denied

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid coordinates"}, status=400)

        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            return JsonResponse({"error": "Out of range"}, status=400)

        profile, _ = UserProfileBalance.objects.get_or_create(
            device_token=device_token
        )
        profile.latitude = latitude
        profile.longitude = longitude
        profile.location_updated_at = timezone.now()
        client_ip = get_client_ip(request)
        if client_ip and client_ip != "unknown" and not profile.ip_address:
            profile.ip_address = client_ip

        profile.save(update_fields=[
            "latitude", "longitude", "location_updated_at", "ip_address"
        ])
        return JsonResponse({"status": "success", "message": "Location updated."})
    except Exception as exc:
        logger.exception("update_user_location failed")
        return JsonResponse({"error": str(exc)}, status=500)