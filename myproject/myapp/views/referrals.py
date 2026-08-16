import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..models import (
    UserProfileBalance,
    ReferralSystem,
    SystemTransactionLog,
)


def get_user_referral_code(
    request,
    device_token,
):

    try:
        profile, _ = (
            UserProfileBalance.objects
            .get_or_create(
                device_token=device_token
            )
        )

        return JsonResponse({
            "status": "success",
            "referral_code": profile.referral_code,
        })

    except Exception as exc:
        return JsonResponse(
            {
                "status": "error",
                "message": str(exc),
            },
            status=500,
        )


@csrf_exempt
def verify_and_apply_referral(request):

    if request.method != "POST":
        return JsonResponse(
            {
                "status": "error",
                "message": "POST required.",
            },
            status=405,
        )

    try:
        data = json.loads(request.body)

        device_token = data.get("device_token")

        referral_code = (
            data.get("referral_code", "")
            .strip()
            .upper()
        )

    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Malformed JSON payload parameters"
                ),
            },
            status=400,
        )

    if not device_token or not referral_code:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Field verification failure! "
                    "device_token and referral_code "
                    "are required."
                ),
            },
            status=400,
        )

    try:

        user_profile, _ = (
            UserProfileBalance.objects
            .get_or_create(
                device_token=device_token
            )
        )

        if (
            ReferralSystem.objects
            .filter(
                referred_user=user_profile
            )
            .exists()
        ):
            return JsonResponse(
                {
                    "status": "error",
                    "message": (
                        "Referral milestone already "
                        "claimed on this device."
                    ),
                },
                status=400,
            )

        if user_profile.referral_code == referral_code:
            return JsonResponse(
                {
                    "status": "error",
                    "message": (
                        "Self-referral operation is invalid."
                    ),
                },
                status=400,
            )

        referrer = (
            UserProfileBalance.objects
            .filter(
                referral_code=referral_code
            )
            .first()
        )

        if not referrer:
            return JsonResponse(
                {
                    "status": "error",
                    "message": (
                        f'The referral code '
                        f'"{referral_code}" does not exist '
                        "in the database."
                    ),
                },
                status=400,
            )

        with transaction.atomic():

            signup_bonus = 50

            user_profile = (
                UserProfileBalance.objects
                .select_for_update()
                .get(id=user_profile.id)
            )

            referrer = (
                UserProfileBalance.objects
                .select_for_update()
                .get(id=referrer.id)
            )

            # Give referred user bonus.
            user_profile.coins += signup_bonus

            user_profile.save(
                update_fields=["coins"]
            )

            # Give referrer bonus.
            referrer.coins += signup_bonus

            referrer.save(
                update_fields=["coins"]
            )

            ReferralSystem.objects.create(
                referrer=referrer,
                referred_user=user_profile,
                total_commission_earned=0,
            )

            SystemTransactionLog.objects.create(
                user_profile=user_profile,
                amount=signup_bonus,
                log_type="REFERRAL_BONUS",
                reference_id=(
                    f"REFERRED_BY_"
                    f"{referrer.referral_code}"
                ),
            )

            SystemTransactionLog.objects.create(
                user_profile=referrer,
                amount=signup_bonus,
                log_type="REFERRAL_BONUS",
                reference_id=(
                    f"INVITED_"
                    f"{user_profile.referral_code}"
                ),
            )

        return JsonResponse({
            "status": "success",
            "message": (
                "Referral applied successfully."
            ),
        })

    except Exception as exc:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Internal Ledger processing failure: "
                    f"{exc}"
                ),
            },
            status=500,
        )