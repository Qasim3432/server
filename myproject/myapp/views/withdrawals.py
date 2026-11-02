# myapp/views/withdrawals.py

import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.http import JsonResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from django.db import transaction

from ..models import (
    WithdrawalRequest,
    UserProfileBalance,
    SystemTransactionLog,
    SystemConfiguration,
    ExchangeRate,
    PK_ONLY_METHODS,
    IN_ONLY_METHODS,
    ALL_REGION_METHODS,
)
from ..services.wager_service import process_withdrawal_approval
from ..currency_utils import format_dollar, convert_cents_to_local
from ..decorators import require_device_owner, require_player_token_owner
from .pin_management import _is_locked, _register_failed_attempt, _reset_attempts


logger = logging.getLogger("myapp.withdrawals")

LOCATION_REQUIRED_AFTER = 6
LOCATION_FRESHNESS_MINUTES = 5
SUPPORTED_WITHDRAW_CURRENCIES = ("INR", "PKR", "USDT", "USD")


def _method_allowed_for_country(method: str, user_country: str | None) -> bool:
    if not method: return False
    method = method.upper().strip()
    if method in ALL_REGION_METHODS: return True
    if method in PK_ONLY_METHODS: return user_country == "PK"
    if method in IN_ONLY_METHODS: return user_country == "IN"
    return False


def _resolve_currency_and_rate(profile, requested_currency, payment_method=None):
    """
    ✅ FIX: Ab currency SIRF method se derive hoti hai.
    User ki requested_currency bilkul ignore hoti hai.

    Pehle:
        User `method: "JAZZCASH"` aur `currency: "USD"` bhej sakta tha.
        `exchange_rate = 1.0` set ho jata tha, `local_amount` USD me
        compute hota tha — admin ko ~280x galat amount dikhta tha.

    Ab:
        Method hi decisive hai. JAZZCASH → PKR, RAZORPAY → INR, USDT → USDT.
        Rate server-controlled `ExchangeRate` model se aati hai.
    """

    method_upper = str(payment_method).upper().strip() if payment_method else ""

    if method_upper in ("JAZZCASH", "EASYPAISA"):
        currency = "PKR"
        rate_obj = ExchangeRate.objects.filter(country="PK").first()
        exchange_rate = (
            Decimal(str(rate_obj.usd_to_local_rate))
            if rate_obj
            else Decimal("280.00")
        )

    elif method_upper in ("RAZORPAY", "PHONEPE"):
        currency = "INR"
        rate_obj = ExchangeRate.objects.filter(country="IN").first()
        exchange_rate = (
            Decimal(str(rate_obj.usd_to_local_rate))
            if rate_obj
            else Decimal("84.00")
        )

    elif method_upper in ("BINANCE", "USDT"):
        currency = "USDT"
        exchange_rate = Decimal("1.0")

    else:
        return None, None, None, JsonResponse(
            {
                "status": "error",
                "code": "INVALID_METHOD",
                "message": f"Unsupported payment method: {payment_method}.",
            },
            status=400,
        )

    if exchange_rate <= 0:
        return None, None, None, JsonResponse(
            {
                "status": "error",
                "code": "RATE_UNAVAILABLE",
                "message": "Exchange rate not configured.",
            },
            status=503,
        )

    return currency, exchange_rate, None, None


def _check_location_requirement(profile):
    approved_count = WithdrawalRequest.objects.filter(
        device_token=profile.device_token, status="APPROVED"
    ).count()
    requires_location = approved_count >= LOCATION_REQUIRED_AFTER
    has_fresh_location = False
    if (
        profile.latitude is not None
        and profile.longitude is not None
        and profile.location_updated_at is not None
    ):
        age = timezone.now() - profile.location_updated_at
        has_fresh_location = age < timedelta(minutes=LOCATION_FRESHNESS_MINUTES)
    return approved_count, requires_location, has_fresh_location


# ==========================================================
# WITHDRAWAL STATUS
#
# ✅ FIX: @require_device_owner — user apna hi status dekh sakta hai
# ==========================================================

@csrf_exempt
@require_device_owner
def get_withdrawal_status(request, device_token):
    profile = UserProfileBalance.objects.filter(device_token=device_token).first()
    if not profile:
        return JsonResponse({"status": "error", "message": "Profile not found."}, status=404)
    approved_count, requires_location, has_fresh_location = _check_location_requirement(profile)
    return JsonResponse({
        "status": "success", "approved_withdrawal_count": approved_count,
        "requires_location": requires_location, "has_location": has_fresh_location,
        "location_freshness_minutes": LOCATION_FRESHNESS_MINUTES,
        "location_required_and_missing": requires_location and not has_fresh_location,
    })


# ==========================================================
# SUBMIT WITHDRAWAL REQUEST
#
# ✅ FIX #1: @require_player_token_owner — body device_token owner verify
# ✅ FIX #2: Idempotency via client_request_id
# ✅ FIX #3: Currency derived from method (server-controlled)
# ==========================================================

@csrf_exempt
def submit_withdrawal_request(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        amount = int(data.get("amount", 0))
        method = data.get("method")
        account_title = data.get("account_title")
        account_number = data.get("account_number")
        pin = str(data.get("pin", "")).strip()
        requested_currency = data.get("currency")  # ✅ Ignored (kept for compat)
        client_request_id = str(data.get("client_request_id", "")).strip()

        if not all([device_token, amount > 0, method, account_title, account_number, pin]):
            return JsonResponse({"status": "error", "message": "Invalid fields."}, status=400)

        # ✅ AUTHZ: X-Auth-Token owner must match body device_token
        denied = require_player_token_owner(request, device_token)
        if denied:
            return denied

        method = str(method).upper().strip()

        with transaction.atomic():
            profile = UserProfileBalance.objects.select_for_update().filter(device_token=device_token).first()
            if not profile:
                return JsonResponse({"status": "error", "message": "User wallet not found."}, status=404)

            # ✅ IDEMPOTENCY: same client_request_id → return cached response
            if client_request_id:
                existing = WithdrawalRequest.objects.filter(
                    device_token=device_token,
                    client_request_id=client_request_id,
                ).first()
                if existing:
                    logger.info(
                        "WITHDRAWAL IDEMPOTENT HIT | device=%s | req_id=%s | existing_id=%s",
                        device_token, client_request_id, existing.id,
                    )
                    return JsonResponse({
                        "status": "success",
                        "message": "Withdrawal already submitted.",
                        "new_balance": profile.coins,
                        "amount": existing.amount,
                        "amount_display": format_dollar(existing.amount),
                        "local_amount": float(existing.local_amount),
                        "currency": existing.currency,
                        "exchange_rate_used": float(existing.exchange_rate_used),
                        "withdrawal_id": existing.id,
                        "duplicate": True,
                    })

            effective_country = profile.country or "PK"
            if not _method_allowed_for_country(method, effective_country):
                return JsonResponse({
                    "status": "error",
                    "code": "METHOD_NOT_ALLOWED",
                    "message": "This payment method is not available in your region.",
                }, status=400)

            currency, exchange_rate, _, error_response = _resolve_currency_and_rate(
                profile, requested_currency, method
            )
            if error_response is not None:
                return error_response

            approved_count, requires_location, has_fresh_location = _check_location_requirement(profile)
            if requires_location and not has_fresh_location:
                return JsonResponse({
                    "status": "error",
                    "code": "LOCATION_REQUIRED",
                    "message": "Fresh location required.",
                }, status=400)

            if not profile.has_withdrawal_pin:
                return JsonResponse({
                    "status": "error",
                    "code": "PIN_NOT_SET",
                    "message": "PIN not set.",
                }, status=400)

            if _is_locked(profile):
                return JsonResponse({
                    "status": "error",
                    "code": "PIN_LOCKED",
                    "message": "Account locked for 12 hours.",
                }, status=423)

            if not check_password(pin, profile.withdrawal_pin_hash):
                locked, attempts_left = _register_failed_attempt(profile, request)
                if locked:
                    return JsonResponse({
                        "status": "error",
                        "code": "PIN_LOCKED",
                        "message": "Account locked for 12 hours.",
                    }, status=400)
                else:
                    return JsonResponse({
                        "status": "error",
                        "code": "PIN_INCORRECT",
                        "message": f"Incorrect PIN. {attempts_left} attempts left.",
                        "attempts_left": attempts_left,
                    }, status=400)

            _reset_attempts(profile)

            if profile.coins < amount:
                return JsonResponse({
                    "status": "error",
                    "message": f"Insufficient balance. Req: {format_dollar(amount)}, Avail: {format_dollar(profile.coins)}.",
                }, status=400)

            local_amount = convert_cents_to_local(amount, exchange_rate)

            profile.coins -= amount
            profile.save(update_fields=["coins"])

            withdrawal = WithdrawalRequest.objects.create(
                user_profile=profile,
                device_token=device_token,
                amount=amount,
                method=method,
                account_title=account_title,
                account_number=account_number,
                status="PENDING",
                local_amount=float(local_amount),
                currency=currency,
                exchange_rate_used=float(exchange_rate),
                client_request_id=client_request_id or None,
            )

            SystemTransactionLog.objects.create(
                user_profile=profile,
                amount=-amount,
                log_type="WITHDRAWAL",
                reference_id=f"REQ_{withdrawal.id}",
            )

            if requires_location:
                profile.location_updated_at = None
                profile.save(update_fields=["location_updated_at"])

        return JsonResponse({
            "status": "success",
            "message": "Withdrawal requested.",
            "new_balance": profile.coins,
            "amount": amount,
            "amount_display": format_dollar(amount),
            "local_amount": float(local_amount),
            "currency": currency,
            "exchange_rate_used": float(exchange_rate),
            "withdrawal_id": withdrawal.id,
        })

    except Exception as exc:
        logger.exception("submit_withdrawal_request failed")
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)


# ==========================================================
# ADMIN — CUSTOM WITHDRAWAL DASHBOARD
# ==========================================================

@staff_member_required
def custom_withdrawal_dashboard(request):
    withdrawals = list(WithdrawalRequest.objects.all().order_by("-created_at")[:200])
    tokens = [w.device_token for w in withdrawals]
    profiles_map = {p.device_token: p for p in UserProfileBalance.objects.filter(device_token__in=tokens)}
    withdrawal_items = [
        {
            "request": w,
            "current_balance": (
                profiles_map.get(w.device_token).coins
                if profiles_map.get(w.device_token) else 0
            ),
            "has_enough": True,
        }
        for w in withdrawals
    ]
    context = {"withdrawal_items": withdrawal_items}
    if request.method == "GET" and request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(request, "withdrawal_table_partial.html", context)
    return render(request, "withdrawal_change_form.html", context)


@staff_member_required
def approve_withdrawal_custom(request, withdraw_id):
    withdrawal = get_object_or_404(WithdrawalRequest, id=withdraw_id, status="PENDING")
    result = process_withdrawal_approval(withdrawal.id)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(result, status=(200 if result["status"] == "success" else 400))
    if result["status"] == "success":
        messages.success(request, result["message"])
    else:
        messages.error(request, result["message"])
    return redirect("custom_withdrawal_dashboard")


@staff_member_required
def reject_withdrawal_custom(request, withdraw_id):
    with transaction.atomic():
        withdrawal = (
            WithdrawalRequest.objects
            .select_for_update()
            .filter(id=withdraw_id, status="PENDING")
            .first()
        )
        if not withdrawal:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"status": "error", "message": "Withdrawal not found."}, status=400)
            messages.error(request, "Withdrawal not found.")
            return redirect("custom_withdrawal_dashboard")

        profile = None
        if withdrawal.user_profile_id:
            profile = UserProfileBalance.objects.select_for_update().filter(id=withdrawal.user_profile_id).first()
        if not profile:
            profile = UserProfileBalance.objects.select_for_update().filter(device_token=withdrawal.device_token).first()

        if profile:
            profile.coins += withdrawal.amount
            profile.save(update_fields=["coins"])
            SystemTransactionLog.objects.create(
                user_profile=profile,
                amount=withdrawal.amount,
                log_type="WITHDRAWAL_REFUND",
                reference_id=f"WD_REJECT_{withdrawal.id}",
            )

        withdrawal.status = "REJECTED"
        withdrawal.save(update_fields=["status"])

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "status": "success",
            "message": "Withdrawal rejected.",
            "refunded_amount": withdrawal.amount,
            "refunded_amount_display": format_dollar(withdrawal.amount),
        })

    messages.warning(request, f"Withdrawal rejected. {format_dollar(withdrawal.amount)} refunded.")
    return redirect("custom_withdrawal_dashboard")