# myapp/views/games.py

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..services.game_service import initialize_game as initialize_game_service
from ..services.wager_service import join_wager
from ..rate_limits import join_wager_rate_limit
from ..decorators import require_player_token_owner     # ✅ P0-6


logger = logging.getLogger("myapp.games")


# ==========================================================
# INITIALIZE GAME
#
# ✅ P0-6 FIX: player_token ownership required
# ==========================================================

@csrf_exempt
def initialize_game(request):

    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed. Use POST."},
            status=405,
        )

    try:
        data = json.loads(request.body)
        player_token = data.get("player_token")
        player_name = data.get("player_name", "Player")
        is_two_player = data.get("is_two_player_mode", True)

        if not player_token:
            return JsonResponse(
                {"error": "Missing player_token attribute."},
                status=400,
            )

        # ✅ P0-6 FIX: token owner check
        denied = require_player_token_owner(request, player_token)
        if denied:
            return denied

        result = initialize_game_service(
            player_token=player_token,
            player_name=player_name,
            is_two_player=is_two_player,
        )

        if result["status"] == "full":
            return JsonResponse(result, status=400)

        return JsonResponse(result)

    except json.JSONDecodeError:
        return JsonResponse(
            {"error": "Malformed JSON request."},
            status=400,
        )

    except Exception as exc:
        logger.exception("initialize_game failed")
        return JsonResponse({"error": str(exc)}, status=500)


# ==========================================================
# JOIN WAGER MATCH
#
# ✅ P0-6 FIX: device_token ownership required
# (was letting user A lock user B's coins)
# ==========================================================

@csrf_exempt
@join_wager_rate_limit
def join_wager_match(request):

    if request.method != "POST":
        return JsonResponse(
            {
                "status": "error",
                "message": "POST request type required",
            },
            status=405,
        )

    try:
        data = json.loads(request.body)
        device_token = data.get("device_token")
        game_id = data.get("game_id")
        bet_amount = int(data.get("bet_amount", 0))

    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse(
            {
                "status": "error",
                "message": "Malformed request payload parameters",
            },
            status=400,
        )

    if not device_token or not game_id or bet_amount <= 0:
        return JsonResponse(
            {
                "status": "error",
                "message": "Missing validation requirements structural fields",
            },
            status=400,
        )

    # ✅ P0-6 FIX: token owner check (CRITICAL — prevents escrow theft)
    denied = require_player_token_owner(request, device_token)
    if denied:
        return denied

    result = join_wager(
        device_token=device_token,
        game_id=game_id,
        bet_amount=bet_amount,
    )

    status_code = 200 if result["status"] == "success" else 400
    return JsonResponse(result, status=status_code)


# ==========================================================
# NOTE
#
# finalize_game_wager and cancel_game_wager are REMOVED.
# Game finalization via WebSocket + sweeper only.
# ==========================================================