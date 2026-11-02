# myapp/views/agora_token.py

import os
import time
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from agora_token_builder import RtcTokenBuilder

from ..services import game_state_store as gss

logger = logging.getLogger(__name__)


# ==========================================================
# AGORA TOKEN GENERATOR
#
# ✅ FIX (issue #3): Game participation verification
#
# Pehle endpoint sirf `channel_name` leta tha — koi check nahi
# ke user us game ka participant hai ya nahi. Koi bhi logged-in
# user kisi bhi game ke voice channel me ghus sakta tha (agar
# channel name pata ho).
#
# Ab:
#   1. X-Auth-Token se auth_user verify (middleware)
#   2. Body device_token == auth_user.device_id
#   3. auth_user.device_id in game_state.player_assignments
#
# Sirf un teen checks ke baad token milta hai.
# ==========================================================

@csrf_exempt
def generate_agora_token(request):
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "Invalid request method"},
            status=405,
        )

    try:
        data = json.loads(request.body)
        channel_name = data.get("channel_name")
        uid = data.get("uid", 0)
        device_token = str(data.get("device_token", "")).strip()

        if not channel_name:
            return JsonResponse(
                {"status": "error", "message": "channel_name is required"},
                status=400,
            )

        # ✅ AUTHZ step 1: middleware guarantees auth_user exists
        auth_user = getattr(request, "auth_user", None)
        if not auth_user:
            return JsonResponse(
                {"status": "error", "message": "Authentication required"},
                status=401,
            )

        # ✅ AUTHZ step 2: body device_token must match authenticated user
        if device_token and device_token != auth_user.device_id:
            logger.warning(
                "AGORA TOKEN AUTHZ FAIL (device mismatch) | "
                "auth=%s body=%s",
                (auth_user.device_id or "?")[:24],
                (device_token or "?")[:24],
            )
            return JsonResponse(
                {"status": "error", "message": "Forbidden"},
                status=403,
            )

        # ✅ AUTHZ step 3: user must be a participant in the game
        game_id = str(channel_name)
        state = gss.get_state(game_id)

        if not state:
            return JsonResponse(
                {"status": "error", "message": "Game not found or expired"},
                status=404,
            )

        assignments = state.get("player_assignments", {})
        if auth_user.device_id not in assignments:
            logger.warning(
                "AGORA TOKEN AUTHZ FAIL (not participant) | "
                "device=%s game=%s",
                (auth_user.device_id or "?")[:24],
                game_id,
            )
            return JsonResponse(
                {"status": "error", "message": "Not a participant in this game"},
                status=403,
            )

        # Optional extra check: game must be LOBBY or ACTIVE
        if state.get("game_status") not in ("LOBBY", "ACTIVE"):
            return JsonResponse(
                {"status": "error", "message": "Game is not active"},
                status=400,
            )

        # ==========================================
        # Generate token
        # ==========================================

        app_id = getattr(settings, "AGORA_APP_ID", os.environ.get("AGORA_APP_ID"))
        app_certificate = getattr(
            settings,
            "AGORA_APP_CERTIFICATE",
            os.environ.get("AGORA_APP_CERTIFICATE"),
        )

        if not app_id or not app_certificate:
            logger.error("Agora credentials not configured in .env")
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Server configuration error: Missing Agora keys",
                },
                status=500,
            )

        expiration_time_in_seconds = 3600
        current_timestamp = int(time.time())
        privilege_expired_ts = current_timestamp + expiration_time_in_seconds

        role = 1  # Publisher

        token = RtcTokenBuilder.buildTokenWithUid(
            app_id,
            app_certificate,
            channel_name,
            int(uid),
            role,
            privilege_expired_ts,
        )

        logger.info(
            "Agora token generated | channel=%s | uid=%s | user=%s",
            channel_name,
            uid,
            (auth_user.device_id or "?")[:24],
        )

        return JsonResponse({
            "status": "success",
            "token": token,
            "app_id": app_id,
            "channel_name": channel_name,
            "uid": uid,
            "expires_at": privilege_expired_ts,
        })

    except Exception as e:
        logger.error(f"Agora token generation failed: {str(e)}")
        return JsonResponse(
            {"status": "error", "message": str(e)},
            status=500,
        )