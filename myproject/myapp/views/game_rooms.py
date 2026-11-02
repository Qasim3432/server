# myapp/views/game_rooms.py

import json
import re
import secrets
import string
import uuid
import logging
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from ..models import GameRoom, UserProfileBalance
from ..services.game_service import get_or_create_game_state, assign_player_color, remove_game_state
from ..services.wager_service import join_wager, cancel_wager
from ..services import game_state_store as gss
from ..decorators import require_player_token_owner

logger = logging.getLogger("myapp.game_rooms")

ROOM_CODE_ALPHABET = string.ascii_uppercase + string.digits
ROOM_CODE_LENGTH = 6
PLAYER_NAME_MAX_LENGTH = 20

# ✅ NEW — Any Unicode whitespace + invisible chars
WHITESPACE_PATTERN = re.compile(r'\s+', re.UNICODE)
ROOM_CODE_CHARS_PATTERN = re.compile(r'[^A-Z0-9]')


def _log_debug(message):
    if getattr(settings, "DEBUG", False):
        print(message)


def _sanitize_room_code(raw):
    """
    ✅ FIX — Aggressively clean room_code.

    WhatsApp copy-paste often injects non-breaking spaces (U+00A0),
    zero-width spaces, or other Unicode whitespace that Python's
    .strip() does NOT remove. This caused "Room not found" 400
    on first join attempt when user pasted with invisible chars.

    Strategy:
      1. Remove ALL Unicode whitespace
      2. Keep only A-Z, 0-9
      3. Uppercase
    """
    if not raw:
        return ""
    s = str(raw)
    s = WHITESPACE_PATTERN.sub("", s)
    s = s.upper()
    s = ROOM_CODE_CHARS_PATTERN.sub("", s)
    return s


def _sanitize_player_name(raw):
    name = (raw or "Player").strip()
    name = "".join(c for c in name if c.isprintable())
    name = name[:PLAYER_NAME_MAX_LENGTH]
    return name if name.strip() else "Player"


def _generate_unique_room_code():
    for _ in range(20):
        code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))
        if not GameRoom.objects.filter(room_code=code).exists():
            return code
    return "RM" + secrets.token_hex(3).upper()


# ✅ NEW — profile pic URL helper (returns None if no pic)
def _get_profile_pic_url(profile):
    if profile and profile.profile_pic and hasattr(profile.profile_pic, 'url'):
        return profile.profile_pic.url
    return None


def _err(message, status=400, code=None):
    payload = {"status": "error", "message": message}
    if code:
        payload["code"] = code
    return JsonResponse(payload, status=status)


@csrf_exempt
def create_private_room(request):
    if request.method != "POST":
        return _err("POST required.", status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        logger.warning("CREATE_ROOM FAIL | Malformed JSON")
        return _err("Malformed JSON.", code="MALFORMED_JSON")

    player_token = data.get("player_token")
    player_name = _sanitize_player_name(data.get("player_name"))
    is_two_player = bool(data.get("is_two_player_mode", True))
    max_players = 2 if is_two_player else 4

    try:
        bet_amount = int(data.get("bet_amount", 0))
    except (ValueError, TypeError):
        logger.warning("CREATE_ROOM FAIL | Invalid bet_amount=%r", data.get("bet_amount"))
        return _err("Invalid bet amount.", code="INVALID_BET")

    if not player_token:
        logger.warning("CREATE_ROOM FAIL | Missing player_token")
        return _err("player_token is required.", code="MISSING_TOKEN")

    if bet_amount <= 0:
        logger.warning("CREATE_ROOM FAIL | bet_amount<=0=%d", bet_amount)
        return _err("bet_amount must be > 0.", code="INVALID_BET")

    profile = UserProfileBalance.objects.filter(device_token=player_token).first()
    if not profile:
        logger.warning("CREATE_ROOM FAIL | No profile | token=%s", player_token)
        return _err("User wallet profile not found.", code="NO_PROFILE")

    if profile.coins < bet_amount:
        logger.warning(
            "CREATE_ROOM FAIL | Insufficient | token=%s coins=%d bet=%d",
            player_token, profile.coins, bet_amount,
        )
        return _err(
            f"Insufficient funds. Required: {bet_amount}, Available: {profile.coins}",
            code="INSUFFICIENT_FUNDS",
        )

    game_id = str(uuid.uuid4())
    room_code = _generate_unique_room_code()

    state = get_or_create_game_state(game_id=game_id, is_two_player=is_two_player)
    state["bet_amount"] = bet_amount
    state["is_private"] = True
    state["room_code"] = room_code
    color = assign_player_color(state, player_token)
    if color is None:
        remove_game_state(game_id)
        logger.warning("CREATE_ROOM FAIL | No color | token=%s", player_token)
        return _err("Failed to assign host color.", code="NO_COLOR")

    if "player_names" not in state:
        state["player_names"] = {}
    state["player_names"][player_token] = player_name

    # ✅ NEW — Save host profile pic for lobby display
    if "player_profiles" not in state:
        state["player_profiles"] = {}
    state["player_profiles"][player_token] = _get_profile_pic_url(profile)

    gss.set_state(game_id, state)

    try:
        GameRoom.objects.create(
            game_id=game_id, bet_amount=bet_amount, game_status="LOBBY",
            total_pool_escrow=0, is_private=True, room_code=room_code,
            max_players=max_players, host_token=player_token,
        )
    except Exception as exc:
        remove_game_state(game_id)
        logger.exception("CREATE_ROOM FAIL | DB create | token=%s", player_token)
        return _err(f"Failed to create room: {exc}", status=500, code="DB_ERROR")

    result = join_wager(device_token=player_token, game_id=game_id, bet_amount=bet_amount)
    if result.get("status") != "success":
        remove_game_state(game_id)
        GameRoom.objects.filter(game_id=game_id).delete()
        logger.warning(
            "CREATE_ROOM FAIL | join_wager | token=%s result=%r",
            player_token, result,
        )
        return _err(result.get("message", "Failed to lock bet."), code="WAGER_FAILED")

    logger.info(
        "CREATE_ROOM OK | code=%s token=%s color=%s bet=%d",
        room_code, player_token, color, bet_amount,
    )

    return JsonResponse({
        "status": "success", "game_id": game_id, "room_code": room_code, "color": color,
        "bet_amount": bet_amount, "game_status": result.get("game_status", "LOBBY"),
        "coins": result.get("coins", profile.coins),
        "locked_coins": result.get("locked_coins", profile.locked_coins),
        "is_two_player_mode": is_two_player, "is_private": True, "max_players": max_players,
    })


@csrf_exempt
def join_private_room(request):
    """
    ✅ REFACTORED — Validation reads OUTSIDE transaction (avoids SQLite
    lock contention with host's room-status polling). Only join_wager
    and state updates carry their own atomicity.
    """

    if request.method != "POST":
        return _err("POST required.", status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        logger.warning("JOIN_ROOM FAIL | Malformed JSON | body=%r", request.body[:200])
        return _err("Malformed JSON.", code="MALFORMED_JSON")

    raw_room_code = data.get("room_code")
    room_code = _sanitize_room_code(raw_room_code)
    player_token = data.get("player_token")
    player_name = _sanitize_player_name(data.get("player_name"))

    if not room_code or not player_token:
        logger.warning(
            "JOIN_ROOM FAIL | Missing fields | raw_code=%r clean_code=%r token=%r",
            raw_room_code, room_code, player_token,
        )
        return _err("room_code and player_token required.", code="MISSING_FIELDS")

    # ==========================================================
    # STEP 1: Validate (READS ONLY — no transaction lock)
    # ==========================================================

    game = GameRoom.objects.filter(room_code=room_code, is_private=True).first()
    if not game:
        logger.warning(
            "JOIN_ROOM FAIL | Room not found | raw=%r clean=%r",
            raw_room_code, room_code,
        )
        return _err("Room not found.", code="ROOM_NOT_FOUND")

    if game.game_status != "LOBBY":
        logger.warning(
            "JOIN_ROOM FAIL | Wrong status | code=%s status=%s",
            room_code, game.game_status,
        )
        return _err(
            f"Room not accepting players. Status: {game.game_status}",
            code="ROOM_NOT_LOBBY",
        )

    if game.players.filter(device_token=player_token).exists():
        state = gss.get_state(game.game_id) or {}
        logger.info(
            "JOIN_ROOM IDEMPOTENT | code=%s token=%s already joined",
            room_code, player_token,
        )
        return JsonResponse({
            "status": "success", "game_id": game.game_id, "room_code": game.room_code,
            "color": state.get("player_assignments", {}).get(player_token),
            "bet_amount": game.bet_amount, "game_status": game.game_status,
            "max_players": game.max_players, "already_joined": True,
        })

    player_count = game.players.count()
    if player_count >= game.max_players:
        logger.warning(
            "JOIN_ROOM FAIL | Room full | code=%s count=%d max=%d",
            room_code, player_count, game.max_players,
        )
        return _err("Room is full.", code="ROOM_FULL")

    profile = UserProfileBalance.objects.filter(device_token=player_token).first()
    if not profile:
        logger.warning("JOIN_ROOM FAIL | No profile | token=%s", player_token)
        return _err("User wallet profile not found.", code="NO_PROFILE")

    if profile.coins < game.bet_amount:
        logger.warning(
            "JOIN_ROOM FAIL | Insufficient | token=%s coins=%d bet=%d",
            player_token, profile.coins, game.bet_amount,
        )
        return _err(
            f"Insufficient funds. Required: {game.bet_amount}, Available: {profile.coins}",
            code="INSUFFICIENT_FUNDS",
        )

    # ==========================================================
    # STEP 2: Lock wager (join_wager has its own transaction + retry)
    # ==========================================================

    result = join_wager(
        device_token=player_token,
        game_id=game.game_id,
        bet_amount=game.bet_amount,
    )

    if result.get("status") != "success":
        logger.warning(
            "JOIN_ROOM FAIL | join_wager | code=%s token=%s result=%r",
            room_code, player_token, result,
        )
        return _err(
            result.get("message", "Failed to lock bet."),
            code="WAGER_FAILED",
        )

    # ==========================================================
    # STEP 3: Update Redis state (no DB writes)
    # ==========================================================

    state = gss.get_state(game.game_id)
    if not state:
        state = get_or_create_game_state(
            game_id=game.game_id,
            is_two_player=(game.max_players == 2),
        )
        state["bet_amount"] = game.bet_amount
        state["is_private"] = True
        state["room_code"] = game.room_code

    color = assign_player_color(state, player_token)
    if color is None:
        logger.warning(
            "JOIN_ROOM FAIL | No color available | code=%s token=%s",
            room_code, player_token,
        )
        # State issue but DB has already locked coins — refund
        cancel_wager(game.game_id)
        return _err("Room is full.", code="ROOM_FULL")

    if "player_names" not in state:
        state["player_names"] = {}
    state["player_names"][player_token] = player_name

    # ✅ NEW — Save joiner profile pic for lobby display
    if "player_profiles" not in state:
        state["player_profiles"] = {}
    state["player_profiles"][player_token] = _get_profile_pic_url(profile)

    gss.set_state(game.game_id, state)

    # ==========================================================
    # STEP 4: Refresh game, activate if full
    # ==========================================================

    game.refresh_from_db()
    if game.game_status == "ACTIVE":
        state["game_status"] = "ACTIVE"
        state["status_text"] = "Game started!"
        gss.set_state(game.game_id, state)

    logger.info(
        "JOIN_ROOM OK | code=%s token=%s color=%s bet=%d",
        room_code, player_token, color, game.bet_amount,
    )

    return JsonResponse({
        "status": "success", "game_id": game.game_id, "room_code": game.room_code,
        "color": color, "bet_amount": game.bet_amount, "game_status": game.game_status,
        "coins": result.get("coins", profile.coins),
        "locked_coins": result.get("locked_coins", profile.locked_coins),
        "is_two_player_mode": game.max_players == 2,
        "is_private": True, "max_players": game.max_players,
    })


@csrf_exempt
def cancel_private_room(request):
    if request.method != "POST":
        return _err("POST required.", status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        logger.warning("CANCEL_ROOM FAIL | Malformed JSON")
        return _err("Malformed JSON.", code="MALFORMED_JSON")

    player_token = data.get("player_token")
    game_id = data.get("game_id")

    if not player_token or not game_id:
        logger.warning("CANCEL_ROOM FAIL | Missing fields")
        return _err("player_token and game_id required.", code="MISSING_FIELDS")

    game = GameRoom.objects.filter(game_id=game_id).first()
    if not game:
        logger.warning("CANCEL_ROOM FAIL | Room not found | game_id=%s", game_id)
        return _err("Room not found.", status=404, code="ROOM_NOT_FOUND")

    if not game.host_token or game.host_token != player_token:
        logger.warning(
            "CANCEL_ROOM FAIL | Not host | game_id=%s token=%s",
            game_id, player_token,
        )
        return _err("Only the room host can cancel this room.", status=403, code="NOT_HOST")

    if game.game_status in ("COMPLETED", "CANCELLED"):
        logger.warning(
            "CANCEL_ROOM FAIL | Wrong status | game_id=%s status=%s",
            game_id, game.game_status,
        )
        return _err(f"Room already {game.game_status}.", code="ROOM_NOT_ACTIVE")

    result = cancel_wager(game_id)
    remove_game_state(game_id)

    if result.get("status") != "success":
        logger.warning(
            "CANCEL_ROOM FAIL | cancel_wager | game_id=%s result=%r",
            game_id, result,
        )
        return _err(result.get("message", "Cancellation failed."), code="CANCEL_FAILED")

    logger.info("CANCEL_ROOM OK | game_id=%s host=%s", game_id, player_token)

    return JsonResponse({
        "status": "success", "message": "Room cancelled.", "game_id": game_id,
        "players_refunded": result.get("players_refunded", 0),
    })


# ==========================================================
# ✅ FIX: get_private_room_status — device_token ownership
#
# Pehle koi bhi logged-in user kisi bhi game ka status fetch
# kar sakta tha. Ab X-Auth-Token owner aur query player_token
# match hone chahiye + game participant hona chahiye.
# ==========================================================

def get_private_room_status(request, game_id):
    player_token = str(request.GET.get("player_token", "")).strip()
    if not player_token:
        return _err("player_token query parameter required.", status=400, code="MISSING_TOKEN")

    # ✅ AUTHZ: X-Auth-Token owner must match player_token
    denied = require_player_token_owner(request, player_token)
    if denied:
        return denied

    game = GameRoom.objects.filter(game_id=game_id).first()
    if not game:
        return _err("Room not found.", status=404, code="ROOM_NOT_FOUND")

    if not game.players.filter(device_token=player_token).exists():
        return _err("Not a participant.", status=403, code="NOT_PARTICIPANT")

    state = gss.get_state(game_id) or {}
    assignments = state.get("player_assignments", {})
    player_names = state.get("player_names", {})

    # ✅ NEW — Read profile pics for lobby payload
    player_profiles = state.get("player_profiles", {})

    players_payload = [
        {
            "device_token": token,
            "color": color,
            "name": player_names.get(token, "Player"),
            "profile_pic": player_profiles.get(token),
        }
        for token, color in assignments.items()
    ]

    return JsonResponse({
        "status": "success", "game_id": game.game_id, "room_code": game.room_code,
        "bet_amount": game.bet_amount, "is_private": game.is_private,
        "game_status": game.game_status, "player_count": len(players_payload),
        "required_players": game.max_players, "players": players_payload,
        "total_pool_escrow": game.total_pool_escrow,
    })