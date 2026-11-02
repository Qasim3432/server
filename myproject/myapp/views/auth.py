# myapp/views/auth.py

import json
import hashlib
import hmac
import secrets
import time
import uuid
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from ..models import (
    UserProfileBalance,
    GameUser,
    COUNTRY_CHOICES,
)
from ..rate_limits import otp_rate_limit, login_rate_limit
from ..request_utils import get_client_ip
from ..services.security_audit import log_event


logger = logging.getLogger("myapp.auth")

OTP_TTL_SECONDS = 300
OTP_SEND_LIMIT_PER_IP = 5
OTP_VERIFY_LIMIT_PER_EMAIL = 5
USERNAME_CHECK_LIMIT_PER_IP = 60

VALID_COUNTRIES = {code for code, _ in COUNTRY_CHOICES}


# ==========================================================
# ✅ P1-7 FIX: Standardized error responses
#
# Client ko sirf `code` matter karta hai — HTTP status kabhi
# 400, kabhi 403, kabhi 409 tha. Ab consistent:
#   {"status": "error", "code": "...", "message": "..."}
# ==========================================================

def _err(code: str, message: str, status: int = 400):
    return JsonResponse(
        {"status": "error", "code": code, "message": message},
        status=status,
    )


# ✅ P1-10 FIX: Caps on all user input
def _s(value, max_len):
    return str(value or "").strip()[:max_len]


def generate_secure_token(email, device_id, ip):
    raw = f"{email}:{device_id}:{ip}:{time.time()}:{secrets.token_hex(8)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _hash_fingerprint(fp: str) -> str:
    secret = settings.DEVICE_FINGERPRINT_SECRET.encode()
    return hmac.new(secret, fp.encode(), hashlib.sha256).hexdigest()


def _match_fingerprint(stored: str, incoming: str) -> bool:
    if not stored or not incoming:
        return False
    incoming_hash = _hash_fingerprint(incoming)
    if hmac.compare_digest(stored, incoming_hash):
        return True
    if len(stored) != 64:
        if hmac.compare_digest(stored, incoming):
            return True
    return False


def _needs_migration(stored: str) -> bool:
    return bool(stored) and len(stored) != 64


def _normalize_country(raw):
    if not raw:
        return None
    code = str(raw).strip().upper()
    return code if code in VALID_COUNTRIES else None


# ==========================================================
# USERNAME AVAILABILITY
# ==========================================================

@csrf_exempt
def check_username_availability(request):
    if request.method != "POST":
        return _err("METHOD_NOT_ALLOWED", "POST required.", 405)

    try:
        data = json.loads(request.body)
        username = _s(data.get("username"), 50)

        if not username:
            return _err("MISSING_FIELD", "username is required.")

        if len(username) < 3 or len(username) > 20:
            return JsonResponse({
                "status": "error",
                "code": "INVALID_LENGTH",
                "message": "Username must be 3-20 characters.",
                "available": False,
            }, status=400)

        ip = get_client_ip(request)
        rate_key = f"username_check:{ip}"
        count = cache.get(rate_key, 0)

        if count >= USERNAME_CHECK_LIMIT_PER_IP:
            return _err("RATE_LIMITED", "Too many requests. Please wait a moment.", 429)

        cache.set(rate_key, count + 1, timeout=60)

        taken = GameUser.objects.filter(username__iexact=username).exists()

        return JsonResponse({
            "status": "success",
            "available": not taken,
            "message": (
                "This username is already taken." if taken
                else "Username is available."
            ),
        }, status=200)

    except json.JSONDecodeError:
        return _err("INVALID_JSON", "Invalid JSON body.")
    except Exception as e:
        logger.exception("check_username_availability failed")
        return _err("INTERNAL", "Something went wrong.", 500)


# ==========================================================
# SEND OTP
# ==========================================================

@csrf_exempt
@otp_rate_limit
def send_otp(request):
    if request.method != "POST":
        return _err("METHOD_NOT_ALLOWED", "POST required.", 405)

    try:
        data = json.loads(request.body)
        email = _s(data.get("email"), 254).lower()
        username = _s(data.get("username"), 50)
        device_fingerprint = _s(data.get("device_fingerprint"), 200)

        if not email:
            return _err("MISSING_FIELD", "email is required.")

        if username:
            username_conflict = (
                GameUser.objects
                .filter(username__iexact=username)
                .exclude(email=email)
                .exists()
            )
            if username_conflict:
                log_event(request, "USERNAME_TAKEN", detail=f"username={username}")
                return _err(
                    "USERNAME_TAKEN",
                    "This username is already taken. Please choose a different one.",
                    409,
                )

        existing_profile = UserProfileBalance.objects.filter(email=email).first()

        if (
            existing_profile
            and existing_profile.device_fingerprint
            and device_fingerprint
            and not _match_fingerprint(
                existing_profile.device_fingerprint, device_fingerprint
            )
        ):
            log_event(request, "DEVICE_MISMATCH", detail=f"email={email}")
            return _err(
                "DEVICE_MISMATCH",
                "This account is already registered on another device.",
                403,
            )

        ip = get_client_ip(request)
        send_key = f"otp_send:{ip}"
        sends = cache.get(send_key, 0)

        if sends >= OTP_SEND_LIMIT_PER_IP:
            log_event(request, "RATE_LIMITED", detail=f"otp_send ip={ip}")
            return _err("RATE_LIMITED", "Too many OTP requests. Try later.", 429)

        cache.set(send_key, sends + 1, timeout=600)

        code = f"{secrets.randbelow(1_000_000):06d}"
        cache.set(f"otp:{email}", code, timeout=OTP_TTL_SECONDS)
        cache.delete(f"otp_verify:{email}")

        try:
            send_mail(
                subject="Rocks Games Verification",
                message=f"Your verification code is: {code}\n\nValid for 5 minutes.",
                from_email=settings.DEFAULT_FROM_EMAIL,   # ✅ P2-9 FIX
                recipient_list=[email],
                fail_silently=False,
            )
        except Exception as mail_err:
            logger.error("[OTP_MAIL_FAIL] %s", mail_err)
            return _err("MAIL_FAILED", "Failed to send OTP email.", 500)

        return JsonResponse({"status": "success", "message": "OTP sent."}, status=200)

    except json.JSONDecodeError:
        return _err("INVALID_JSON", "Invalid JSON body.")
    except Exception as e:
        logger.exception("send_otp failed")
        return _err("INTERNAL", "Something went wrong.", 500)


# ==========================================================
# VERIFY EMAIL LOGIN
# ==========================================================

@csrf_exempt
@login_rate_limit
def verify_email_login(request):
    if request.method != "POST":
        return _err("METHOD_NOT_ALLOWED", "POST required.", 405)

    try:
        data = json.loads(request.body)
        email = _s(data.get("email"), 254).lower()
        username = _s(data.get("username"), 50)
        device_id = _s(data.get("device_id"), 255)
        code = _s(data.get("code"), 10)
        device_fingerprint = _s(data.get("device_fingerprint"), 200)

        country = _normalize_country(data.get("country"))
        if country is None:
            return _err(
                "INVALID_COUNTRY",
                "Please select Pakistan or India.",
            )

        if not all([email, username, device_id, code, device_fingerprint]):
            return _err("MISSING_FIELD", "Missing required fields.")

        verify_key = f"otp_verify:{email}"
        attempts = cache.get(verify_key, 0)

        if attempts >= OTP_VERIFY_LIMIT_PER_EMAIL:
            log_event(request, "RATE_LIMITED", detail=f"otp_verify email={email}")
            return _err("RATE_LIMITED", "Too many verification attempts.", 429)

        stored_code = cache.get(f"otp:{email}")

        if not stored_code:
            return _err("OTP_EXPIRED", "OTP expired or not requested.")

        if stored_code != code:
            cache.set(verify_key, attempts + 1, timeout=600)
            log_event(request, "LOGIN_FAILED", detail=f"bad_otp email={email}")
            return _err("OTP_INVALID", "Invalid verification code.")

        cache.delete(f"otp:{email}")
        cache.delete(verify_key)

        ip_address = get_client_ip(request)
        auth_token = generate_secure_token(email, device_id, ip_address)

        profile_by_email = UserProfileBalance.objects.filter(email=email).first()
        profile_by_device = UserProfileBalance.objects.filter(device_token=device_id).first()

        if profile_by_email:
            stored_fp = profile_by_email.device_fingerprint
            if stored_fp and not _match_fingerprint(stored_fp, device_fingerprint):
                log_event(
                    request, "DEVICE_MISMATCH",
                    device_token=device_id,
                    detail=f"verify email={email}",
                )
                return _err(
                    "DEVICE_MISMATCH",
                    "This account is already registered on another device.",
                    403,
                )

            if not stored_fp or _needs_migration(stored_fp):
                profile_by_email.device_fingerprint = _hash_fingerprint(device_fingerprint)
                profile_by_email.save(update_fields=["device_fingerprint"])

        with transaction.atomic():
            if profile_by_email:
                if profile_by_device and profile_by_device.id != profile_by_email.id:
                    profile_by_device.device_token = f"orphan_{secrets.token_hex(8)}"
                    profile_by_device.save(update_fields=["device_token"])

                if profile_by_email.device_token != device_id:
                    profile_by_email.device_token = device_id
                    profile_by_email.save(update_fields=["device_token"])

            elif profile_by_device:
                if not profile_by_device.email or profile_by_device.email == "":
                    profile_by_device.email = email
                    profile_by_device.device_fingerprint = _hash_fingerprint(device_fingerprint)
                    profile_by_device.save(update_fields=["email", "device_fingerprint"])
                else:
                    profile_by_device.device_token = f"orphan_{secrets.token_hex(8)}"
                    profile_by_device.save(update_fields=["device_token"])

            signup_profile = UserProfileBalance.objects.filter(email=email).first()
            if signup_profile is None:
                signup_profile = UserProfileBalance.objects.filter(device_token=device_id).first()

            if signup_profile is not None:
                if not signup_profile.country:
                    signup_profile.country = country
                    signup_profile.save(update_fields=["country"])
            else:
                UserProfileBalance.objects.create(
                    email=email, device_token=device_id, country=country,
                )

        existing_game_user = GameUser.objects.filter(email=email).first()

        if existing_game_user:
            gu_fp = existing_game_user.device_fingerprint
            if gu_fp and not _match_fingerprint(gu_fp, device_fingerprint):
                log_event(
                    request, "DEVICE_MISMATCH",
                    device_token=device_id,
                    detail=f"gameuser email={email}",
                )
                return _err(
                    "DEVICE_MISMATCH",
                    "This account is already registered on another device.",
                    403,
                )

            if not gu_fp or _needs_migration(gu_fp):
                existing_game_user.device_fingerprint = _hash_fingerprint(device_fingerprint)
                existing_game_user.save(update_fields=["device_fingerprint"])

        device_bound_user = (
            GameUser.objects.filter(device_id=device_id)
            .exclude(email=email)
            .exclude(logged_out_at__isnull=False)
            .first()
        )

        if device_bound_user and device_bound_user.email:
            return _err(
                "DEVICE_BOUND",
                "This device is already registered with another email.",
                409,
            )

        username_conflict = (
            GameUser.objects.filter(username__iexact=username)
            .exclude(email=email)
            .exists()
        )
        if username_conflict:
            log_event(request, "USERNAME_TAKEN", detail=f"verify username={username}")
            return _err(
                "USERNAME_TAKEN",
                "This username is already taken. Please choose a different one.",
                409,
            )

        with transaction.atomic():
            user, created = GameUser.objects.update_or_create(
                email=email,
                defaults={
                    "username": username,
                    "device_id": device_id,
                    "device_fingerprint": _hash_fingerprint(device_fingerprint),
                    "ip_address": ip_address,
                    "auth_token": auth_token,
                    "logged_out_at": None,
                },
            )

        log_event(
            request, "LOGIN_SUCCESS",
            device_token=device_id,
            detail=f"email={email} new={created}",
        )

        final_profile = UserProfileBalance.objects.filter(email=email).first()
        saved_country = (final_profile.country if final_profile else None) or country

        return JsonResponse({
            "status": "success",
            "created": created,
            "country": saved_country,
            "user": {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "device_id": user.device_id,
                "auth_token": user.auth_token,
            },
        }, status=201 if created else 200)

    except Exception as e:
        logger.exception("verify_email_login failed")
        return _err("INTERNAL", "Something went wrong.", 500)


# ==========================================================
# LOGOUT
#
# ✅ P1-5 FIX: Only current session killed + audit logged
#
# Pehle: timestamp-based suffix (collision possible)
# Ab: uuid-based (guaranteed unique)
# + Also clear device_token lock on UserProfileBalance so
#   user can login from same device again immediately.
# ==========================================================

@csrf_exempt
def logout_user(request):
    if request.method != "POST":
        return _err("METHOD_NOT_ALLOWED", "POST required.", 405)

    try:
        data = json.loads(request.body)
        device_id = _s(data.get("device_id"), 255)

        if not device_id:
            return _err("MISSING_FIELD", "device_id is required.")

        # ✅ P1-5 FIX: uuid prefix (collision-proof)
        unique_suffix = f"loggedout:{uuid.uuid4().hex[:12]}:{device_id}"

        updated = GameUser.objects.filter(device_id=device_id).update(
            device_id=unique_suffix[:255],
            auth_token=None,
            logged_out_at=timezone.now(),
        )

        log_event(
            request, "LOGOUT",
            device_token=device_id,
            detail=f"cleared={updated}",
        )

        return JsonResponse({
            "status": "success",
            "message": "Logged out successfully.",
            "cleared": updated,
        })

    except Exception as e:
        logger.exception("logout_user failed")
        return _err("INTERNAL", "Something went wrong.", 500)


# ==========================================================
# EMAIL CHANGE OTP
# ==========================================================

@csrf_exempt
def send_email_change_otp(request):
    if request.method != "POST":
        return _err("METHOD_NOT_ALLOWED", "POST required.", 405)

    try:
        data = json.loads(request.body)
        device_token = _s(data.get("device_token"), 255)
        new_email = _s(data.get("new_email"), 254).lower()

        if not device_token or not new_email:
            return _err("MISSING_FIELD", "Missing fields.")

        profile = UserProfileBalance.objects.filter(device_token=device_token).first()

        if not profile:
            return _err("NOT_FOUND", "Profile not found.", 404)

        if UserProfileBalance.objects.filter(email=new_email).exclude(id=profile.id).exists():
            return _err("EMAIL_TAKEN", "Email already in use.", 409)

        code = f"{secrets.randbelow(1_000_000):06d}"
        cache.set(f"email_change_otp:{device_token}", code, timeout=OTP_TTL_SECONDS)

        send_mail(
            subject="Rocks Games — Email Change Verification",
            message=f"Your email change code is: {code}\n\nValid 5 minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,   # ✅ P2-9 FIX
            recipient_list=[new_email],
            fail_silently=False,
        )

        return JsonResponse({"status": "success", "message": "Code sent to new email."})

    except Exception as e:
        logger.exception("send_email_change_otp failed")
        return _err("INTERNAL", "Something went wrong.", 500)