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
        is_multipart = (
            request.content_type
            and "multipart" in request.content_type
        )

        if is_multipart:
            device_token = request.POST.get("device_token")
            nickname = request.POST.get("nickname")
            email = request.POST.get("email")
            profile_pic_file = request.FILES.get("profile_pic")
        else:
            data = json.loads(request.body)

            device_token = data.get("device_token")
            nickname = data.get("nickname")
            email = data.get("email")
            profile_pic_file = None

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

            if email:
                if (
                    UserProfileBalance.objects
                    .filter(email=email)
                    .exclude(pk=profile.pk)
                    .exists()
                ):
                    return JsonResponse(
                        {
                            "error": "Email already in use"
                        },
                        status=400,
                    )
                profile.email = email

            if profile_pic_file:
                profile.profile_pic = profile_pic_file

            profile.save()

        pic_url = None

        if profile.profile_pic:
            pic_url = request.build_absolute_uri(
                profile.profile_pic.url
            )

        return JsonResponse(
            {
                "status": "success",
                "message": (
                    "Identity verified and saved successfully!"
                ),
                "profile_pic_url": pic_url,
            }
        )

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