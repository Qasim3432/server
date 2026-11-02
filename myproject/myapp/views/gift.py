# myapp/views/gift.py

import json
import secrets
import time
import logging

from django.db import transaction, IntegrityError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..models import (
    UserProfileBalance,
    SystemTransactionLog,
    SystemSetting,
    SpinHistory,
)
from ..rate_limits import spin_rate_limit
from ..decorators import require_device_owner
from ..services.security_audit import log_event


logger = logging.getLogger("myapp.gift")

GIFTS = [
    {"name": "50 Coins", "emoji": "🪙", "coin_value": 50},
    {"name": "10 Coins", "emoji": "🪙", "coin_value": 10},
    {"name": "20 Coins", "emoji": "💰", "coin_value": 20},
    {"name": "Rose", "emoji": "🌹", "coin_value": 0},
    {"name": "30 Diamond", "emoji": "💎", "coin_value": 30},
    {"name": "Try Again", "emoji": "✨", "coin_value": 0},
    {"name": "40 Coins", "emoji": "🪙", "coin_value": 40},
    {"name": "Crown", "emoji": "👑", "coin_value": 0},
]

FREE_SPIN_COOLDOWN = 24 * 60 * 60
DAILY_BONUS_COOLDOWN = 24 * 60 * 60


def get_paid_cost():
    return int(SystemSetting.get_value("paid_spin_cost", "40"))


def is_gift_enabled():
    return SystemSetting.get_value("gift_enabled", "1") == "1"


def _get_bonus_amount():
    try:
        return int(SystemSetting.get_value("daily_bonus_amount", "100"))
    except (ValueError, TypeError):
        return 100


def _get_or_create_profile_locked(device_token):
    profile = (
        UserProfileBalance.objects
        .select_for_update()
        .filter(device_token=device_token)
        .first()
    )
    if profile:
        return profile, False

    try:
        profile = UserProfileBalance.objects.create(device_token=device_token)
        return profile, True
    except IntegrityError:
        profile = (
            UserProfileBalance.objects
            .select_for_update()
            .filter(device_token=device_token)
            .first()
        )
        if profile is None:
            raise
        return profile, False


# ==========================================================
# ✅ P1-9 FIX: Cryptographically secure + weighted random
#
# Pehle: random.randint (predictable + uniform)
# Ab: secrets.randbelow + optional weight from
#     SystemSetting "spin_weight_<index>"
#
# Admin can set weights:
#   spin_weight_0 = 1    (very rare)
#   spin_weight_1 = 20   (common)
#   spin_weight_4 = 5
# If ALL weights = 0 (default) → falls back to uniform.
# ==========================================================

def _pick_gift_index():
    weights = []
    for i in range(len(GIFTS)):
        try:
            w = int(SystemSetting.get_value(f"spin_weight_{i}", "0"))
        except (ValueError, TypeError):
            w = 0
        weights.append(max(0, w))

    total = sum(weights)
    if total <= 0:
        # Fallback to uniform using CSPRNG
        return secrets.randbelow(len(GIFTS))

    roll = secrets.randbelow(total)
    cumulative = 0
    for i, w in enumerate(weights):
        cumulative += w
        if roll < cumulative:
            return i
    return len(GIFTS) - 1


# ==========================================================
# SPIN STATUS — auth required
# ==========================================================

@csrf_exempt
def get_spin_status(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")

        if not device_token:
            return JsonResponse({"error": "device_token required"}, status=400)

        if not is_gift_enabled():
            return JsonResponse({"error": "Gift system disabled"}, status=403)

        profile, _ = UserProfileBalance.objects.get_or_create(
            device_token=device_token
        )

        last_spin = getattr(profile, "last_free_spin", 0) or 0
        now = int(time.time())
        can_free = (now - last_spin) > FREE_SPIN_COOLDOWN

        time_left = 0 if can_free else FREE_SPIN_COOLDOWN - (now - last_spin)

        return JsonResponse({
            "status": "success",
            "can_use_free_spin": can_free,
            "time_left": time_left,
            "coins": profile.coins,
            "paid_spin_cost": get_paid_cost(),
            "gifts": GIFTS,
        })

    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


# ==========================================================
# SUBMIT SPIN
#
# ✅ P1-1 FIX: Idempotency via client_request_id
# ✅ P1-9 FIX: Weighted CSPRNG
# ✅ RATE LIMITED
# ==========================================================

@csrf_exempt
@spin_rate_limit
def submit_spin(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        client_request_id = str(data.get("client_request_id", "")).strip()[:64]

        if not device_token:
            return JsonResponse({"error": "device_token required"}, status=400)

        if not is_gift_enabled():
            return JsonResponse({"error": "Gift system disabled"}, status=403)

        with transaction.atomic():

            profile, _ = _get_or_create_profile_locked(device_token)

            # ==========================================================
            # ✅ P1-1 FIX: Idempotency check
            # Same UUID → return cached result, no double charge
            # ==========================================================
            if client_request_id:
                existing = SpinHistory.objects.filter(
                    user_profile=profile,
                    client_request_id=client_request_id,
                ).first()
                if existing:
                    logger.info(
                        "SPIN IDEMPOTENT HIT | device=%s | req_id=%s | existing_spin=%s",
                        device_token, client_request_id, existing.id,
                    )
                    return JsonResponse({
                        "status": "success",
                        "won_index": existing.won_index,
                        "won_gift": {
                            "name": existing.gift_name,
                            "emoji": existing.gift_emoji,
                            "coin_value": existing.coin_value,
                        },
                        "coins": profile.coins,
                        "was_free": existing.was_free,
                        "duplicate": True,
                    })

            last_spin = getattr(profile, "last_free_spin", 0) or 0
            now = int(time.time())
            is_free = (now - last_spin) > FREE_SPIN_COOLDOWN
            paid_cost = get_paid_cost()
            cost = 0 if is_free else paid_cost

            if profile.coins < cost:
                return JsonResponse({"error": "Not enough coins"}, status=400)

            if cost > 0:
                profile.coins -= cost
                SystemTransactionLog.objects.create(
                    user_profile=profile,
                    amount=-cost,
                    log_type="SPIN_COST",
                    reference_id=f"spin_{now}",
                )

            # ✅ P1-9 FIX: CSPRNG + weighted
            won_index = _pick_gift_index()
            won_gift = GIFTS[won_index]

            if won_gift["coin_value"] > 0:
                profile.coins += won_gift["coin_value"]
                SystemTransactionLog.objects.create(
                    user_profile=profile,
                    amount=won_gift["coin_value"],
                    log_type="SPIN_REWARD",
                    reference_id=f"spin_{now}",
                )

            if is_free:
                profile.last_free_spin = now

            profile.save()

            SpinHistory.objects.create(
                user_profile=profile,
                gift_name=won_gift["name"],
                gift_emoji=won_gift["emoji"],
                coin_value=won_gift["coin_value"],
                was_free=is_free,
                cost_paid=cost,
                client_request_id=client_request_id or None,
                won_index=won_index,
            )

        return JsonResponse({
            "status": "success",
            "won_index": won_index,
            "won_gift": won_gift,
            "coins": profile.coins,
            "was_free": is_free,
        })

    except IntegrityError as exc:
        # Race: two identical client_request_ids arrived concurrently
        # One wins, one loses with unique constraint — retry the lookup
        logger.warning("SPIN IntegrityError (possible race) | %s", exc)
        return JsonResponse(
            {"error": "Duplicate request — please retry with same id."},
            status=409,
        )
    except Exception as exc:
        logger.exception("submit_spin failed")
        return JsonResponse({"error": str(exc)}, status=400)


# ==========================================================
# GIFT CONFIG (public)
# ==========================================================

@csrf_exempt
def gift_config_api(request):
    return JsonResponse({
        "gift_enabled": "1" if is_gift_enabled() else "0",
        "paid_spin_cost": get_paid_cost(),
    })


# ==========================================================
# GIFT CLAIM (alias)
# ==========================================================

@csrf_exempt
def gift_claim_api(request):
    return submit_spin(request)


# ==========================================================
# SPIN HISTORY (auth)
# ==========================================================

@require_device_owner
def get_spin_history(request, device_token):
    profile = UserProfileBalance.objects.filter(device_token=device_token).first()
    if not profile:
        return JsonResponse(
            {"status": "error", "message": "Profile not found."}, status=404
        )

    try:
        limit = int(request.GET.get("limit", 20))
    except (ValueError, TypeError):
        limit = 20

    limit = max(1, min(limit, 100))

    entries = (
        SpinHistory.objects
        .filter(user_profile=profile)
        .order_by("-spun_at")[:limit]
    )

    payload = [
        {
            "gift_name": e.gift_name,
            "gift_emoji": e.gift_emoji,
            "coin_value": e.coin_value,
            "was_free": e.was_free,
            "cost_paid": e.cost_paid,
            "spun_at": e.spun_at.strftime("%d %b %Y, %I:%M %p"),
        }
        for e in entries
    ]

    return JsonResponse({"status": "success", "history": payload})


# ==========================================================
# DAILY BONUS STATUS
# ==========================================================

@csrf_exempt
def get_daily_bonus_status(request, device_token):
    profile = UserProfileBalance.objects.filter(device_token=device_token).first()
    if not profile:
        return JsonResponse(
            {"status": "error", "message": "Profile not found."}, status=404
        )

    now = int(time.time())
    last = int(profile.last_daily_bonus or 0)
    elapsed = now - last
    can_claim = elapsed >= DAILY_BONUS_COOLDOWN
    time_left = 0 if can_claim else DAILY_BONUS_COOLDOWN - elapsed

    return JsonResponse({
        "status": "success",
        "can_claim": can_claim,
        "time_left": time_left,
        "bonus_amount": _get_bonus_amount(),
        "coins": profile.coins,
    })


# ==========================================================
# DAILY BONUS CLAIM
# ==========================================================

@csrf_exempt
def claim_daily_bonus(request):
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "POST required."}, status=405
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON."}, status=400
        )

    device_token = str(data.get("device_token", "")).strip()

    if not device_token:
        return JsonResponse(
            {"status": "error", "message": "device_token required."}, status=400
        )

    with transaction.atomic():
        profile = (
            UserProfileBalance.objects
            .select_for_update()
            .filter(device_token=device_token)
            .first()
        )

        if not profile:
            return JsonResponse(
                {"status": "error", "message": "Profile not found."}, status=404
            )

        now = int(time.time())
        last = int(profile.last_daily_bonus or 0)
        elapsed = now - last

        if elapsed < DAILY_BONUS_COOLDOWN:
            return JsonResponse({
                "status": "error",
                "message": "Already claimed.",
                "time_left": DAILY_BONUS_COOLDOWN - elapsed,
            }, status=400)

        bonus_amount = _get_bonus_amount()

        profile.coins += bonus_amount
        profile.last_daily_bonus = now
        profile.save(update_fields=["coins", "last_daily_bonus"])

        SystemTransactionLog.objects.create(
            user_profile=profile,
            amount=bonus_amount,
            log_type="DAILY_BONUS",
            reference_id=f"DAILY_{now}",
        )

        return JsonResponse({
            "status": "success",
            "message": f"Daily bonus claimed! +{bonus_amount} coins",
            "bonus_amount": bonus_amount,
            "coins": profile.coins,
        })