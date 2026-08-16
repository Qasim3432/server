# views/auth.py

import json

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..models import UserProfileBalance


@csrf_exempt
def create_test_user(request):
    """
    DEVELOPMENT / TESTING ONLY.

    Creates or updates a test UserProfileBalance.

    This endpoint is disabled when DEBUG=False.
    """

    if request.method != "POST":
        return JsonResponse(
            {
                "status": "error",
                "message": "POST required."
            },
            status=405
        )

    if not settings.DEBUG:
        return JsonResponse(
            {
                "status": "error",
                "message": "Test user creation is disabled."
            },
            status=403
        )

    try:
        data = json.loads(request.body)

        device_token = str(
            data.get("device_token", "")
        ).strip()

        nickname = str(
            data.get("nickname", "Test Player")
        ).strip()

        phone_number = str(
            data.get("phone_number", "")
        ).strip()

        if not device_token:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "device_token is required."
                },
                status=400
            )

        if not phone_number:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "phone_number is required."
                },
                status=400
            )

        # --------------------------------------------------
        # Check whether this device already exists
        # --------------------------------------------------

        existing_device = UserProfileBalance.objects.filter(
            device_token=device_token
        ).first()

        # --------------------------------------------------
        # Check whether phone belongs to another device
        # --------------------------------------------------

        existing_phone = UserProfileBalance.objects.filter(
            phone_number=phone_number
        ).first()

        if existing_phone and (
            not existing_device
            or existing_phone.id != existing_device.id
        ):
            return JsonResponse(
                {
                    "status": "error",
                    "message": "This phone number is already registered.",
                    "existing_device_token": existing_phone.device_token
                },
                status=409
            )

        # --------------------------------------------------
        # Create / update profile
        # --------------------------------------------------

        with transaction.atomic():

            profile, created = (
                UserProfileBalance.objects.get_or_create(
                    device_token=device_token
                )
            )

            profile.nickname = nickname
            profile.phone_number = phone_number
            profile.save()

        return JsonResponse(
            {
                "status": "success",
                "created": created,
                "user": {
                    "device_token": profile.device_token,
                    "nickname": profile.nickname,
                    "phone_number": profile.phone_number,
                    "coins": profile.coins,
                    "locked_coins": profile.locked_coins,
                    "referral_code": profile.referral_code,
                }
            },
            status=201 if created else 200
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {
                "status": "error",
                "message": "Invalid JSON body."
            },
            status=400
        )

    except Exception as e:
        return JsonResponse(
            {
                "status": "error",
                "message": str(e)
            },
            status=500
        )