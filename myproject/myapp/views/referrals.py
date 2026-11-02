# myapp/views/referrals.py

import json
import logging
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from ..models import UserProfileBalance, ReferralSystem, SystemTransactionLog, SystemSetting
from ..decorators import require_device_owner


logger = logging.getLogger("myapp.referrals")


def _get_signup_bonus():
    try:
        return int(SystemSetting.get_value("referral_signup_bonus", "50"))
    except (ValueError, TypeError):
        return 50


def _get_invite_reward():
    try:
        return int(SystemSetting.get_value("referral_invite_reward", "50"))
    except (ValueError, TypeError):
        return 50


# ==========================================================
# GET REFERRAL CODE — public GET
#
# Note: Ye endpoint public hai kyunki referral code share karne
# ke liye hai. Koi privacy concern nahi — ye publicly shareable
# hai by design.
# ==========================================================

def get_user_referral_code(request, device_token):
    try:
        profile, _ = UserProfileBalance.objects.get_or_create(device_token=device_token)
        if not profile.referral_code:
            profile.save()
            profile.refresh_from_db()
        return JsonResponse({"status": "success", "referral_code": profile.referral_code})
    except Exception as exc:
        logger.exception("get_user_referral_code failed")
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)


@csrf_exempt
def verify_and_apply_referral(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        referral_code = (data.get("referral_code", "").strip().upper())
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"status": "error", "message": "Malformed payload"}, status=400)

    if not device_token or not referral_code:
        return JsonResponse({"status": "error", "message": "Missing fields."}, status=400)

    try:
        with transaction.atomic():
            user_profile, _ = UserProfileBalance.objects.get_or_create(device_token=device_token)
            user_profile = UserProfileBalance.objects.select_for_update().get(id=user_profile.id)

            if ReferralSystem.objects.filter(referred_user=user_profile).exists():
                return JsonResponse({"status": "error", "message": "Referral already claimed."}, status=400)
            if user_profile.referral_code == referral_code:
                return JsonResponse({"status": "error", "message": "Self-referral invalid."}, status=400)

            referrer = UserProfileBalance.objects.select_for_update().filter(referral_code=referral_code).first()
            if not referrer:
                return JsonResponse({"status": "error", "message": f'Code "{referral_code}" does not exist.'}, status=400)

            signup_bonus = _get_signup_bonus()
            invite_reward = _get_invite_reward()

            user_profile.coins += signup_bonus
            user_profile.save(update_fields=["coins"])
            SystemTransactionLog.objects.create(
                user_profile=user_profile,
                amount=signup_bonus,
                log_type="REFERRAL_BONUS",
                reference_id=f"REFERRED_BY_{referrer.referral_code}",
            )

            ReferralSystem.objects.create(
                referrer=referrer,
                referred_user=user_profile,
                total_commission_earned=0,
                referrer_reward_amount=invite_reward,
            )
            logger.info(
                "REFERRAL APPLIED | new=%s | referrer=%s | bonus=%s",
                user_profile.device_token, referrer.device_token, signup_bonus,
            )

        return JsonResponse({"status": "success", "message": "Referral applied.", "signup_bonus": signup_bonus})
    except Exception as exc:
        logger.exception("verify_and_apply_referral failed")
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)


# ==========================================================
# REFERRAL DASHBOARD — auth required
#
# ✅ FIX: @require_device_owner
#
# Pehle koi bhi logged-in user kisi ka bhi referral dashboard
# fetch kar sakta tha sirf device_token pata hone pe. Isme
# referred users ki list, earnings, commission — sab sensitive
# data leak hota tha.
#
# Ab X-Auth-Token owner aur URL device_token match hone chahiye.
# ==========================================================

@require_device_owner
def get_referral_dashboard(request, device_token):
    profile = UserProfileBalance.objects.filter(device_token=device_token).first()
    if not profile:
        return JsonResponse({"status": "error", "message": "Profile not found."}, status=404)

    if not profile.referral_code:
        profile.save()
        profile.refresh_from_db()

    referrals = ReferralSystem.objects.filter(referrer=profile).select_related("referred_user").order_by("-created_at")
    total_commission = sum(r.total_commission_earned or 0 for r in referrals)
    pending_rewards = referrals.filter(referrer_reward_paid=False).count()

    referred_list = []
    for r in referrals[:50]:
        referred = r.referred_user
        pic_url = None
        if referred.profile_pic:
            try:
                pic_url = referred.profile_pic.url
            except Exception:
                pass
        referred_list.append({
            "name": referred.nickname or "Player",
            "profile_pic": pic_url,
            "joined_at": r.created_at.strftime("%d %b %Y"),
            "commission_earned": r.total_commission_earned or 0,
            "reward_paid": r.referrer_reward_paid,
            "reward_amount": r.referrer_reward_amount or 0,
        })

    return JsonResponse({
        "status": "success",
        "referral_code": profile.referral_code,
        "total_referred": referrals.count(),
        "total_commission_earned": total_commission,
        "pending_rewards": pending_rewards,
        "referred_users": referred_list,
    })