# myapp/views/pin_management.py

import json
import secrets
import time
import logging

from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.cache import cache
from django.core.mail import send_mail
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..models import UserProfileBalance
from ..services.security_audit import log_event

logger = logging.getLogger("myapp.pin")

PIN_LENGTH = 4
PIN_RESET_OTP_TTL = 300
PIN_RESET_SEND_LIMIT = 3
PIN_RESET_VERIFY_LIMIT = 5

PIN_MAX_ATTEMPTS = 5
PIN_LOCKOUT_SECONDS = 12 * 60 * 60


# ==========================================================
# ✅ P1-6: PIN SECURITY NOTES
#
# 4-digit PIN = 10,000 combinations. With 5 attempts + 12h lockout:
#   - max 5 tries per 12h
#   - full brute-force = 2000 days (~5.5 years)
#   - Safe against remote brute force
#
# BUT:
#   - Susceptible to shoulder surfing (short PIN)
#   - Fixed PIN = long-term secret
#
# FUTURE UPGRADE PATH (P3):
#   - 6-digit PIN (1,000,000 combinations)
#   - PIN expiry (force change every 90 days)
#   - Biometric fallback via Android KeyStore
# ==========================================================


def _is_valid_pin(pin):
    return isinstance(pin, str) and len(pin) == PIN_LENGTH and pin.isdigit()


def _get_profile(device_token):
    return UserProfileBalance.objects.filter(device_token=device_token).first()


def _is_locked(profile):
    return int(profile.withdrawal_pin_locked_until or 0) > int(time.time())


def _register_failed_attempt(profile, request, detail=""):
    profile.withdrawal_pin_failed_attempts = (
        profile.withdrawal_pin_failed_attempts or 0
    ) + 1

    if profile.withdrawal_pin_failed_attempts >= PIN_MAX_ATTEMPTS:
        profile.withdrawal_pin_locked_until = int(time.time()) + PIN_LOCKOUT_SECONDS
        profile.withdrawal_pin_failed_attempts = 0
        profile.save(
            update_fields=[
                "withdrawal_pin_failed_attempts",
                "withdrawal_pin_locked_until",
            ]
        )
        log_event(
            request, "PIN_LOCKED",
            device_token=profile.device_token,
            detail=f"locked for 12h {detail}",
        )
        return True, 0

    profile.save(update_fields=["withdrawal_pin_failed_attempts"])
    attempts_left = PIN_MAX_ATTEMPTS - profile.withdrawal_pin_failed_attempts
    log_event(
        request, "PIN_INCORRECT",
        device_token=profile.device_token,
        detail=f"attempts_left={attempts_left} {detail}",
    )
    return False, attempts_left


def _reset_attempts(profile):
    profile.withdrawal_pin_failed_attempts = 0
    profile.withdrawal_pin_locked_until = 0
    profile.save(
        update_fields=[
            "withdrawal_pin_failed_attempts",
            "withdrawal_pin_locked_until",
        ]
    )


@csrf_exempt
def get_pin_status(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        if not device_token:
            return JsonResponse(
                {"status": "error", "message": "device_token is required."}, status=400
            )

        profile = _get_profile(device_token)
        if not profile:
            return JsonResponse(
                {"status": "error", "message": "Profile not found."}, status=404
            )

        return JsonResponse({
            "status": "success",
            "has_withdrawal_pin": profile.has_withdrawal_pin,
            "has_email": bool(profile.email),
            "is_locked": _is_locked(profile),
            "locked_until": int(profile.withdrawal_pin_locked_until or 0),
            "failed_attempts": int(profile.withdrawal_pin_failed_attempts or 0),
            "max_attempts": PIN_MAX_ATTEMPTS,
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def set_withdrawal_pin(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        pin = str(data.get("pin", "")).strip()
        confirm_pin = str(data.get("confirm_pin", "")).strip()

        if not device_token:
            return JsonResponse(
                {"status": "error", "message": "device_token is required."}, status=400
            )
        if not _is_valid_pin(pin):
            return JsonResponse(
                {"status": "error", "message": f"PIN must be {PIN_LENGTH} digits."},
                status=400,
            )
        if pin != confirm_pin:
            return JsonResponse(
                {"status": "error", "message": "PINs do not match."}, status=400
            )

        profile = _get_profile(device_token)
        if not profile:
            return JsonResponse(
                {"status": "error", "message": "Profile not found."}, status=404
            )
        if profile.has_withdrawal_pin:
            return JsonResponse(
                {"status": "error", "message": "PIN already set."}, status=400
            )

        profile.withdrawal_pin_hash = make_password(pin)
        profile.has_withdrawal_pin = True
        profile.save(update_fields=["withdrawal_pin_hash", "has_withdrawal_pin"])
        _reset_attempts(profile)

        log_event(request, "PIN_SET", device_token=device_token)

        return JsonResponse({"status": "success", "message": "Withdrawal PIN set successfully."})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def change_withdrawal_pin(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        old_pin = str(data.get("old_pin", "")).strip()
        new_pin = str(data.get("new_pin", "")).strip()
        confirm_pin = str(data.get("confirm_pin", "")).strip()

        if not device_token or not _is_valid_pin(old_pin) or not _is_valid_pin(new_pin):
            return JsonResponse(
                {"status": "error", "message": "Invalid fields/PIN format."}, status=400
            )
        if new_pin != confirm_pin:
            return JsonResponse(
                {"status": "error", "message": "New PINs do not match."}, status=400
            )

        profile = _get_profile(device_token)
        if not profile or not profile.has_withdrawal_pin:
            return JsonResponse({"status": "error", "message": "No PIN set."}, status=400)

        if _is_locked(profile):
            return JsonResponse(
                {"status": "error", "message": "PIN locked. Try after 12 hours."},
                status=423,
            )

        if not check_password(old_pin, profile.withdrawal_pin_hash):
            locked, attempts_left = _register_failed_attempt(
                profile, request, detail="change_pin"
            )
            if locked:
                return JsonResponse({
                    "status": "error",
                    "message": "Old PIN is incorrect. Locked for 12 hours.",
                    "code": "PIN_LOCKED",
                }, status=400)
            return JsonResponse({
                "status": "error",
                "message": f"Old PIN is incorrect. {attempts_left} attempts left.",
                "code": "PIN_INCORRECT",
                "attempts_left": attempts_left,
            }, status=400)

        profile.withdrawal_pin_hash = make_password(new_pin)
        profile.save(update_fields=["withdrawal_pin_hash"])
        _reset_attempts(profile)

        log_event(request, "PIN_CHANGED", device_token=device_token)

        return JsonResponse({"status": "success", "message": "PIN changed successfully."})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def reset_pin_send_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        if not device_token:
            return JsonResponse(
                {"status": "error", "message": "device_token is required."}, status=400
            )

        cooldown_key = f"pin_reset_cooldown:{device_token}"
        if cache.get(cooldown_key):
            return JsonResponse({
                "status": "error",
                "message": "Please wait 2 hours before requesting another PIN reset.",
            }, status=429)

        profile = _get_profile(device_token)
        if not profile or not profile.email:
            return JsonResponse(
                {"status": "error", "message": "No profile or email on file."}, status=400
            )

        send_key = f"pin_reset_send:{device_token}"
        sends = cache.get(send_key, 0)
        if sends >= PIN_RESET_SEND_LIMIT:
            return JsonResponse(
                {"status": "error", "message": "Too many reset requests."}, status=429
            )

        cache.set(send_key, sends + 1, timeout=600)

        otp_code = f"{secrets.randbelow(1_000_000):06d}"
        cache.set(f"pin_reset_otp:{device_token}", otp_code, timeout=PIN_RESET_OTP_TTL)
        cache.delete(f"pin_reset_verify:{device_token}")

        cache.set(cooldown_key, True, timeout=2 * 60 * 60)

        send_mail(
            subject="Rocks Games — PIN Reset Code",
            message=f"Your PIN reset code is: {otp_code}\n\nValid for 5 minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,   # ✅ P2-9 FIX
            recipient_list=[profile.email],
            fail_silently=False,
        )

        log_event(request, "PIN_RESET_REQUESTED", device_token=device_token)

        email = profile.email
        local, domain = email.split("@", 1)
        masked_email = (
            f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"
            if len(local) > 2
            else f"{local[0]}*@{domain}"
        )

        return JsonResponse({
            "status": "success",
            "message": f"Reset code sent to {masked_email}.",
            "masked_email": masked_email,
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def reset_pin_verify_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        otp_code = str(data.get("otp_code", "")).strip()
        new_pin = str(data.get("new_pin", "")).strip()
        confirm_pin = str(data.get("confirm_pin", "")).strip()

        if (
            not device_token
            or not otp_code
            or not _is_valid_pin(new_pin)
            or new_pin != confirm_pin
        ):
            return JsonResponse(
                {"status": "error", "message": "Invalid fields."}, status=400
            )

        verify_key = f"pin_reset_verify:{device_token}"
        attempts = cache.get(verify_key, 0)
        if attempts >= PIN_RESET_VERIFY_LIMIT:
            return JsonResponse(
                {"status": "error", "message": "Too many attempts."}, status=429
            )

        stored_otp = cache.get(f"pin_reset_otp:{device_token}")
        if not stored_otp:
            return JsonResponse(
                {"status": "error", "message": "OTP expired."}, status=400
            )
        if stored_otp != otp_code:
            cache.set(verify_key, attempts + 1, timeout=600)
            return JsonResponse(
                {"status": "error", "message": "Invalid OTP."}, status=400
            )

        cache.delete(f"pin_reset_otp:{device_token}")
        cache.delete(verify_key)

        profile = _get_profile(device_token)
        if not profile:
            return JsonResponse(
                {"status": "error", "message": "Profile not found."}, status=404
            )

        profile.withdrawal_pin_hash = make_password(new_pin)
        profile.has_withdrawal_pin = True
        profile.save(update_fields=["withdrawal_pin_hash", "has_withdrawal_pin"])
        _reset_attempts(profile)

        log_event(request, "PIN_SET", device_token=device_token, detail="via_reset")

        return JsonResponse({"status": "success", "message": "PIN reset successfully."})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)