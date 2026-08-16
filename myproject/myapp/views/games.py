import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..services.game_service import initialize_game as initialize_game_service
from ..services.wager_service import (
    join_wager,
    finalize_wager,
    cancel_wager,
)


# ==========================================
# GAME INITIALIZATION
# ==========================================

@csrf_exempt
def initialize_game(request):

    if request.method != "POST":
        return JsonResponse(
            {
                "error": "Method not allowed. Use POST."
            },
            status=405,
        )

    try:
        data = json.loads(request.body)

        player_token = data.get("player_token")
        is_two_player = data.get(
            "is_two_player_mode",
            True,
        )

        if not player_token:
            return JsonResponse(
                {
                    "error": (
                        "Missing player_token attribute."
                    )
                },
                status=400,
            )

        result = initialize_game_service(
            player_token=player_token,
            is_two_player=is_two_player,
        )

        if result["status"] == "full":
            return JsonResponse(
                result,
                status=400,
            )

        return JsonResponse(result)

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


# ==========================================
# WAGER JOIN
# ==========================================

@csrf_exempt
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
        bet_amount = int(
            data.get("bet_amount", 0)
        )

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Malformed request payload parameters"
                ),
            },
            status=400,
        )

    if not device_token or not game_id or bet_amount <= 0:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Missing validation requirements "
                    "structural fields"
                ),
            },
            status=400,
        )

    result = join_wager(
        device_token=device_token,
        game_id=game_id,
        bet_amount=bet_amount,
    )

    status_code = (
        200
        if result["status"] == "success"
        else 400
    )

    return JsonResponse(
        result,
        status=status_code,
    )


# ==========================================
# GAME FINALIZATION
# ==========================================

@csrf_exempt
def finalize_game_wager(request):

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

        game_id = data.get("game_id")
        winning_device_token = data.get(
            "winning_device_token"
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {
                "status": "error",
                "message": "Malformed JSON input parameters",
            },
            status=400,
        )

    if not game_id or not winning_device_token:
        return JsonResponse(
            {
                "status": "error",
                "message": "game_id and winning_device_token are required",
            },
            status=400,
        )

    result = finalize_wager(
        game_id=game_id,
        winning_device_token=winning_device_token,
    )

    status_code = (
        200
        if result["status"] == "success"
        else 400
    )

    return JsonResponse(
        result,
        status=status_code,
    )


# ==========================================
# GAME CANCELLATION
# ==========================================

@csrf_exempt
def cancel_game_wager(request):

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
        game_id = data.get("game_id")

    except json.JSONDecodeError:
        return JsonResponse(
            {
                "status": "error",
                "message": "Malformed request parameters",
            },
            status=400,
        )

    if not game_id:
        return JsonResponse(
            {
                "status": "error",
                "message": "game_id is required",
            },
            status=400,
        )

    result = cancel_wager(game_id)

    status_code = (
        200
        if result["status"] == "success"
        else 400
    )

    return JsonResponse(
        result,
        status=status_code,
    )