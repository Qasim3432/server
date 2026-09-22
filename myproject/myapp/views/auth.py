# views/auth.py

import json
import hashlib
import time

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail

from..models import UserProfileBalance
from..models import GameUser

def generate_secure_token(email, device_id, ip):
    """
    Token mixture of IP + device + email.
    """
    raw = f"{email}:{device_id}:{ip}:{time.time()}"
    return hashlib.sha256(raw.encode()).hexdigest()

@csrf_exempt
def send_otp(request):
    """
    Send OTP to user email for verification.
    Takes email and code.
    """

    if request.method!= "POST":
        return JsonResponse(
            {
                "status": "error",
                "message": "POST required."
            },
            status=405
        )

    try:
        data = json.loads(request.body)

        email = str(
            data.get("email", "")
        ).strip().lower()

        code = str(
            data.get("code", "")
        ).strip()

        if not email:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "email is required."
                },
                status=400
            )

        if not code:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "code is required."
                },
                status=400
            )

        send_mail(
            'Rocks Games Verification',
            f'Tumhara verification code hai: {code}',
            'bedrockentertainent@gmail.com',
            [email],
            fail_silently=False,
        )

        return JsonResponse(
            {
                "status": "success",
                "message": "OTP sent."
            },
            status=200
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

@csrf_exempt
def verify_email_login(request):
    """
    Email auth with Gmail verification.
    Takes email, username, device_id.
    Creates secure token as mixture of IP + device + email.
    Stores token in device and backend.
    """

    if request.method!= "POST":
        return JsonResponse(
            {
                "status": "error",
                "message": "POST required."
            },
            status=405
        )

    try:
        data = json.loads(request.body)

        email = str(
            data.get("email", "")
        ).strip().lower()

        username = str(
            data.get("username", "")
        ).strip()

        device_id = str(
            data.get("device_id", "")
        ).strip()

        if not email:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "email is required."
                },
                status=400
            )

        if not username:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "username is required."
                },
                status=400
            )

        if not device_id:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "device_id is required."
                },
                status=400
            )

        ip_address = request.META.get("REMOTE_ADDR")

        auth_token = generate_secure_token(
            email,
            device_id,
            ip_address
        )

        existing_email = GameUser.objects.filter(
            email=email
        ).first()

        existing_device = GameUser.objects.filter(
            device_id=device_id
        ).first()

        if existing_email and (
            not existing_device
            or existing_email.id!= existing_device.id
        ):
            return JsonResponse(
                {
                    "status": "error",
                    "message": "This email is already registered with another device.",
                },
                status=409
            )

        with transaction.atomic():
            user, created = GameUser.objects.update_or_create(
                email=email,
                defaults={
                    "username": username,
                    "device_id": device_id,
                    "ip_address": ip_address,
                    "auth_token": auth_token,
                }
            )

        return JsonResponse(
            {
                "status": "success",
                "created": created,
                "user": {
                    "user_id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "device_id": user.device_id,
                    "auth_token": user.auth_token,
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