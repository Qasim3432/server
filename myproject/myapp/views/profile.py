# myapp/views/profile.py

import json

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..models import UserProfileBalance, GameUser


NICKNAME_MIN = 2
NICKNAME_MAX = 20

# ✅ FIX (issue #14): File size / content type validation constants
# Puri file me apply karte hain, sirf ek jagah nahi.
MAX_PIC_SIZE = getattr(settings, "MAX_PROFILE_PIC_SIZE", 2 * 1024 * 1024)
ALLOWED_PIC_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}


@csrf_exempt
def update_user_profile(request):

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

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
                {"error": "Missing parameters"},
                status=400,
            )

        nickname = str(nickname).strip()

        if len(nickname) < NICKNAME_MIN or len(nickname) > NICKNAME_MAX:
            return JsonResponse(
                {
                    "error": (
                        f"Nickname must be between "
                        f"{NICKNAME_MIN} and {NICKNAME_MAX} characters."
                    )
                },
                status=400,
            )

        email = str(email).strip() if email else ""

        # ==========================================================
        # ✅ FIX (issue #14): Profile pic size + content-type check
        #
        # Pehle koi validation nahi thi — user 100MB file upload kar
        # sakta tha aur disk fill ho jati thi. Ab max 2MB aur sirf
        # image types allow hain.
        # ==========================================================

        if profile_pic_file is not None:
            if profile_pic_file.size > MAX_PIC_SIZE:
                return JsonResponse(
                    {
                        "error": (
                            f"Profile picture too large. "
                            f"Max {MAX_PIC_SIZE // (1024 * 1024)}MB allowed."
                        )
                    },
                    status=400,
                )

            content_type = (profile_pic_file.content_type or "").lower()
            if content_type not in ALLOWED_PIC_TYPES:
                return JsonResponse(
                    {
                        "error": (
                            "Unsupported image format. "
                            "Please use JPG, PNG, or WebP."
                        )
                    },
                    status=400,
                )

        with transaction.atomic():

            profile, created = (
                UserProfileBalance.objects
                .select_for_update()
                .get_or_create(device_token=device_token)
            )

            update_fields = []

            if profile.nickname != nickname:
                name_taken = (
                    UserProfileBalance.objects
                    .filter(nickname__iexact=nickname)
                    .exclude(pk=profile.pk)
                    .exists()
                )
                if name_taken:
                    return JsonResponse(
                        {"error": "This username is already taken. Please choose another."},
                        status=409,
                    )

                profile.nickname = nickname
                update_fields.append("nickname")

            if email and profile.email != email:

                email_taken = (
                    UserProfileBalance.objects
                    .filter(email=email)
                    .exclude(pk=profile.pk)
                    .exists()
                )

                if email_taken:
                    return JsonResponse(
                        {"error": "This email is already registered to another account."},
                        status=409,
                    )

                profile.email = email
                update_fields.append("email")

            if profile_pic_file:
                profile.profile_pic = profile_pic_file
                update_fields.append("profile_pic")

            if update_fields:
                try:
                    profile.save(update_fields=update_fields)

                    if "nickname" in update_fields and profile.email:
                        GameUser.objects.filter(email=profile.email).update(username=nickname)

                except IntegrityError as ie:
                    if "email" in str(ie).lower():
                        return JsonResponse(
                            {
                                "error": (
                                    "This email is already registered "
                                    "to another account."
                                )
                            },
                            status=409,
                        )
                    raise

        pic_url = None
        if profile.profile_pic:
            pic_url = request.build_absolute_uri(profile.profile_pic.url)

        return JsonResponse({
            "status": "success",
            "message": "Identity verified and saved successfully!",
            "profile_pic_url": pic_url,
            "nickname": profile.nickname,
            "email": profile.email or "",
            "country": profile.country or "",
        })

    except json.JSONDecodeError:
        return JsonResponse(
            {"error": "Malformed JSON request."},
            status=400,
        )

    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)