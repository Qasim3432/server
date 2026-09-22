import json
import random
import time

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..models import (
    UserProfileBalance,
    SystemTransactionLog,
    SystemSetting,
)

# tumhare Kotlin screen wale gifts
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

def get_paid_cost():
    return int(
        SystemSetting.get_value(
            "paid_spin_cost",
            "40",
        )
    )

def is_gift_enabled():
    return (
        SystemSetting.get_value(
            "gift_enabled",
            "1",
        )
        == "1"
    )

# ==========================================
# SPIN STATUS
# ==========================================

@csrf_exempt
def get_spin_status(request):

    if request.method != "POST":
        return JsonResponse(
            {"error": "POST required"},
            status=405,
        )

    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")

        if not device_token:
            return JsonResponse(
                {"error": "device_token required"},
                status=400,
            )

        if not is_gift_enabled():
            return JsonResponse(
                {"error": "Gift system disabled"},
                status=403,
            )

        profile, _ = (
            UserProfileBalance.objects
            .get_or_create(
                device_token=device_token
            )
        )

        last_spin = (
            getattr(
                profile,
                "last_free_spin",
                0,
            )
            or 0
        )

        now = int(time.time())

        can_free = (
            now - last_spin
        ) > FREE_SPIN_COOLDOWN

        time_left = (
            0 if can_free
            else FREE_SPIN_COOLDOWN - (now - last_spin)
        )

        return JsonResponse({
            "status": "success",
            "can_use_free_spin": can_free,
            "time_left": time_left,
            "coins": profile.coins,
            "paid_spin_cost": get_paid_cost(),
            "gifts": GIFTS,
        })

    except Exception as exc:
        return JsonResponse(
            {"error": str(exc)},
            status=400,
        )

# ==========================================
# SUBMIT SPIN
# ==========================================

@csrf_exempt
def submit_spin(request):

    if request.method != "POST":
        return JsonResponse(
            {"error": "POST required"},
            status=405,
        )

    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")

        if not device_token:
            return JsonResponse(
                {"error": "device_token required"},
                status=400,
            )

        if not is_gift_enabled():
            return JsonResponse(
                {"error": "Gift system disabled"},
                status=403,
            )

        with transaction.atomic():

            profile, _ = (
                UserProfileBalance.objects
                .select_for_update()
                .get_or_create(
                    device_token=device_token
                )
            )

            last_spin = (
                getattr(
                    profile,
                    "last_free_spin",
                    0,
                )
                or 0
            )

            now = int(time.time())

            is_free = (
                now - last_spin
            ) > FREE_SPIN_COOLDOWN

            paid_cost = get_paid_cost()

            cost = 0 if is_free else paid_cost

            if profile.coins < cost:
                return JsonResponse(
                    {"error": "Not enough coins"},
                    status=400,
                )

            if cost > 0:
                profile.coins -= cost

                SystemTransactionLog.objects.create(
                    user_profile=profile,
                    amount=-cost,
                    log_type="SPIN_COST",
                    reference_id=f"spin_{now}",
                )

            won_index = random.randint(
                0,
                len(GIFTS) - 1,
            )

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

        return JsonResponse({
            "status": "success",
            "won_index": won_index,
            "won_gift": won_gift,
            "coins": profile.coins,
            "was_free": is_free,
        })

    except Exception as exc:
        return JsonResponse(
            {"error": str(exc)},
            status=400,
        )

# ==========================================
# GIFT CONFIG - for Android frontend
# ==========================================

@csrf_exempt
def gift_config_api(request):
    return JsonResponse({
        "gift_enabled": "1" if is_gift_enabled() else "0",
        "paid_spin_cost": get_paid_cost(),
    })

# ==========================================
# GIFT CLAIM - alias for submit_spin logic
# ==========================================

@csrf_exempt
def gift_claim_api(request):
    # tumhara submit_spin hi claim hai, is liye usko call kar do
    return submit_spin(request)