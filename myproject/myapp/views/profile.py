import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..models import UserProfileBalance


@csrf_exempt
def update_user_profile(request):

    if request.method != "POST":
        return JsonResponse(
            {
                "error": "Method not allowed"
            },
            status=405,
        )

    try:
        data = json.loads(request.body)

        device_token = data.get("device_token")
        nickname = data.get("nickname")
        phone = data.get("phone_number")

        if not device_token or not nickname:
            return JsonResponse(
                {
                    "error": "Missing parameters"
                },
                status=400,
            )

        with transaction.atomic():

            profile, created = (
                UserProfileBalance.objects
                .get_or_create(
                    device_token=device_token
                )
            )

            profile.nickname = nickname
            profile.phone_number = phone

            profile.save(
                update_fields=[
                    "nickname",
                    "phone_number",
                ]
            )

        return JsonResponse({
            "status": "success",
            "message": (
                "Identity verified and saved successfully!"
            ),
        })

    except json.JSONDecodeError:
        return JsonResponse(
            {
                "error": "Malformed JSON request."
            },
            status=400,
        )

    except Exception as exc:
        return JsonResponse(
            {
                "error": str(exc)
            },
            status=500,
        )