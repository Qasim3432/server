# myapp/views/deposits.py

import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required

from ..models import (
    DepositRequest,
    UserProfileBalance,
    SystemTransactionLog,
    ReferralSystem,
    SystemSetting,
    SystemConfiguration,
    ExchangeRate,
    PK_ONLY_METHODS,
    IN_ONLY_METHODS,
    ALL_REGION_METHODS,
)
from ..currency_utils import format_dollar, format_local_currency, convert_local_to_cents
from ..decorators import require_player_token_owner     # ✅ P0-5

logger = logging.getLogger("myapp.deposits")

DEPOSIT_BONUS_DEFAULT = 10
DEPOSIT_BONUS_COOLDOWN_HOURS = 24
DEPOSIT_MAX_AGE_DAYS = 7


def _get_deposit_bonus():
    try:
        return int(SystemSetting.get_value("deposit_bonus_coins", str(DEPOSIT_BONUS_DEFAULT)))
    except (ValueError, TypeError):
        return DEPOSIT_BONUS_DEFAULT


def _is_bonus_eligible(profile):
    if not profile:
        return False
    cutoff = timezone.now() - timedelta(hours=DEPOSIT_BONUS_COOLDOWN_HOURS)
    return not SystemTransactionLog.objects.filter(
        user_profile=profile,
        log_type="DEPOSIT_BONUS",
        timestamp__gte=cutoff,
    ).exists()


def _method_allowed_for_country(method: str, user_country: str | None) -> bool:
    if not method:
        return False
    method = method.upper().strip()
    if method in ALL_REGION_METHODS:
        return True
    if method in PK_ONLY_METHODS:
        return user_country == "PK"
    if method in IN_ONLY_METHODS:
        return user_country == "IN"
    return False


@csrf_exempt
def submit_deposit_request(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        local_amount = Decimal(str(data.get("local_amount", 0)))
        currency = str(data.get("currency", "USD")).upper()
        method = data.get("payment_method")
        sender_name = data.get("sender_name", "")

        if not device_token or local_amount <= 0 or not method:
            return JsonResponse({"error": "Invalid payload"}, status=400)

        # ✅ P0-5 FIX: X-Auth-Token owner must match body device_token
        denied = require_player_token_owner(request, device_token)
        if denied:
            return denied

        method = str(method).upper().strip()

        linked_profile = UserProfileBalance.objects.filter(device_token=device_token).first()
        user_country = linked_profile.country if linked_profile else None
        if not user_country:
            user_country = "PK"

        if not _method_allowed_for_country(method, user_country):
            return JsonResponse(
                {
                    "status": "error",
                    "code": "METHOD_NOT_ALLOWED",
                    "message": "This payment method is not available in your region.",
                },
                status=400,
            )

        config = SystemConfiguration.get_solo()
        exchange_rate = Decimal("1.0")

        if method == "USDT":
            currency = "USDT"
            exchange_rate = Decimal("1.0")
            usd_cents = int(round(local_amount * Decimal("100")))
        else:
            if currency == "INR":
                rate_obj = ExchangeRate.objects.filter(country="IN").first()
                exchange_rate = Decimal(str(rate_obj.usd_to_local_rate)) if rate_obj else Decimal("84.00")
            elif currency == "PKR":
                rate_obj = ExchangeRate.objects.filter(country="PK").first()
                exchange_rate = Decimal(str(rate_obj.usd_to_local_rate)) if rate_obj else Decimal("280.00")
            elif method in IN_ONLY_METHODS:
                currency = "INR"
                rate_obj = ExchangeRate.objects.filter(country="IN").first()
                exchange_rate = Decimal(str(rate_obj.usd_to_local_rate)) if rate_obj else Decimal("84.00")
            elif method in PK_ONLY_METHODS:
                currency = "PKR"
                rate_obj = ExchangeRate.objects.filter(country="PK").first()
                exchange_rate = Decimal(str(rate_obj.usd_to_local_rate)) if rate_obj else Decimal("280.00")
            elif currency not in ("USD",):
                currency = "USD"
                exchange_rate = Decimal("1.0")

            usd_cents = convert_local_to_cents(local_amount, exchange_rate)

        if usd_cents <= 0:
            return JsonResponse({"error": "Amount too small"}, status=400)

        DepositRequest.objects.create(
            user_profile=linked_profile,
            device_token=device_token,
            amount=usd_cents,
            local_amount=float(local_amount),
            currency=currency,
            exchange_rate_used=float(exchange_rate),
            payment_method=method,
            sender_name=sender_name,
            status="PENDING",
        )

        return JsonResponse({"status": "success", "message": "Verification submitted!"})

    except Exception as exc:
        logger.exception("submit_deposit_request failed")
        return JsonResponse({"error": str(exc)}, status=400)


# =========================================================
# (rest of admin views unchanged — same as original)
# =========================================================

@staff_member_required
def custom_deposit_dashboard(request):
    deposits = DepositRequest.objects.all().order_by("-created_at")
    context = {"deposit_items": deposits}
    if request.method == "GET" and request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(request, "deposit_table_partial.html", context)
    return render(request, "deposit_change_form.html", context)


@staff_member_required
def approve_deposit_custom(request, deposit_id):
    referrer_reward = 0
    bonus_credited = 0
    bonus_skipped = False

    with transaction.atomic():
        deposit = DepositRequest.objects.select_for_update().filter(id=deposit_id, status="PENDING").first()
        if not deposit:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": "Deposit not found or already processed."}, status=400)
            messages.error(request, "Deposit not found.")
            return redirect("custom_deposit_dashboard")

        if deposit.created_at < timezone.now() - timedelta(days=DEPOSIT_MAX_AGE_DAYS):
            msg = f"Deposit older than {DEPOSIT_MAX_AGE_DAYS} days. Reject instead."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg}, status=400)
            messages.error(request, msg)
            return redirect("custom_deposit_dashboard")

        profile = None
        if deposit.user_profile_id:
            profile = UserProfileBalance.objects.select_for_update().filter(id=deposit.user_profile_id).first()
        if not profile:
            profile = UserProfileBalance.objects.select_for_update().filter(device_token=deposit.device_token).first()
            if profile:
                deposit.user_profile = profile
                deposit.save(update_fields=["user_profile"])
        if not profile:
            profile = UserProfileBalance.objects.create(device_token=deposit.device_token)
            deposit.user_profile = profile
            deposit.save(update_fields=["user_profile"])

        profile.coins += deposit.amount
        if deposit.currency != "USD":
            profile.currency = deposit.currency
        is_first = not profile.has_made_first_deposit
        if is_first:
            profile.has_made_first_deposit = True
        profile.save(update_fields=["coins", "currency", "has_made_first_deposit"])

        deposit.status = "APPROVED"
        deposit.save(update_fields=["status"])

        SystemTransactionLog.objects.create(
            user_profile=profile,
            amount=deposit.amount,
            log_type="DEPOSIT",
            reference_id=str(deposit.id),
        )

        bonus_amount = _get_deposit_bonus()
        if bonus_amount > 0 and _is_bonus_eligible(profile):
            profile.coins += bonus_amount
            profile.save(update_fields=["coins"])
            SystemTransactionLog.objects.create(
                user_profile=profile,
                amount=bonus_amount,
                log_type="DEPOSIT_BONUS",
                reference_id=f"BONUS_{deposit.id}",
            )
            bonus_credited = bonus_amount
        elif bonus_amount > 0:
            bonus_skipped = True

        if is_first:
            referral = ReferralSystem.objects.select_for_update().filter(
                referred_user=profile, referrer_reward_paid=False
            ).first()
            if referral and referral.referrer:
                referrer = UserProfileBalance.objects.select_for_update().filter(id=referral.referrer.id).first()
                if referrer:
                    reward_amount = referral.referrer_reward_amount or 50
                    referrer.coins += reward_amount
                    referrer.save(update_fields=["coins"])
                    referral.referrer_reward_paid = True
                    referral.total_commission_earned += reward_amount
                    referral.save(update_fields=["referrer_reward_paid", "total_commission_earned"])
                    SystemTransactionLog.objects.create(
                        user_profile=referrer,
                        amount=reward_amount,
                        log_type="REFERRAL_INVITE_REWARD",
                        reference_id=f"INVITE_{deposit.id}",
                    )
                    referrer_reward = reward_amount

    msg_parts = [
        f"Approved {format_local_currency(deposit.local_amount, deposit.currency)} "
        f"(Credited: {format_dollar(deposit.amount)})."
    ]
    if bonus_credited > 0:
        msg_parts.append(f"🎁 +{format_dollar(bonus_credited)} bonus.")
    elif bonus_skipped:
        msg_parts.append("⏭️ Bonus skipped (24h cooldown).")
    if referrer_reward > 0:
        msg_parts.append(f"Referrer got {format_dollar(referrer_reward)}.")

    final_msg = " ".join(msg_parts)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "success", "message": final_msg})
    messages.success(request, final_msg)
    return redirect("custom_deposit_dashboard")


@staff_member_required
def reject_deposit_custom(request, deposit_id):
    with transaction.atomic():
        deposit = DepositRequest.objects.select_for_update().filter(id=deposit_id, status="PENDING").first()
        if not deposit:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": "Not found."}, status=400)
            return redirect("custom_deposit_dashboard")
        deposit.status = "REJECTED"
        deposit.save(update_fields=["status"])

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "success", "message": "Rejected."})
    messages.error(request, "Rejected deposit.")
    return redirect("custom_deposit_dashboard")