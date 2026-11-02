# myapp/services/game_service.py

import time
import uuid
import logging

from django.db import transaction
from ..models import UserProfileBalance, SystemSetting
from ..currency_utils import format_dollar
from . import game_state_store as gss

logger = logging.getLogger("myapp.services.game_service")

# Matchmaking race window
MATCHMAKING_RETRIES = 6
MATCHMAKING_RETRY_DELAY = 0.15   # seconds


def is_gift_enabled():
    return SystemSetting.get_value("gift_enabled", "1") == "1"


def get_spin_cost():
    try:
        return int(SystemSetting.get_value("paid_spin_cost", "40"))
    except (ValueError, TypeError):
        return 40


def can_user_spin(profile):
    if not is_gift_enabled():
        return False, "Gift system disabled by admin"
    return True, "allowed"


from .game_state import (
    get_or_create_game_state,
    assign_player_color,
    remove_game_state,
)


def _cleanup_stale_lobby(game_id):
    from .wager_service import cancel_wager

    # ✅ Remove from waiting index BEFORE deleting state
    state = gss.get_state(game_id)
    if state:
        is_two = state.get("is_two_player_mode", True)
        bet = int(state.get("bet_amount", 0))
        if bet > 0 and not state.get("is_private", False):
            gss.remove_waiting_room(game_id, is_two, bet)
        # Clear player_lobby pointers for all participants
        for token in state.get("player_assignments", {}).keys():
            gss.clear_player_lobby(token)

    try:
        cancel_wager(str(game_id))
    except Exception:
        logger.exception(
            "STALE LOBBY refund failed | Game=%s", game_id,
        )

    try:
        gss.delete_state(str(game_id))
    except Exception:
        logger.exception(
            "STALE LOBBY state delete failed | Game=%s", game_id,
        )

    logger.info(
        "STALE LOBBY cleaned + refunded | Game=%s", game_id,
    )


# ==========================================================
# MATCHMAKING — uses waiting room index
#
# ✅ O(M) where M = waiting lobbies matching mode+bet,
# instead of O(N) where N = ALL game states.
#
# Fallback: if bet_amount is None (older clients), we still
# fall back to iter_all_states() — but new clients pass bet.
# ==========================================================

def find_waiting_room(
    is_two_player=True,
    player_token=None,
    bet_amount=None,
):

    now = time.time()
    required_players = 2 if is_two_player else 4

    # Fast path: use waiting index
    if bet_amount is not None:
        try:
            bet_int = int(bet_amount)
        except (ValueError, TypeError):
            bet_int = 0

        if bet_int > 0:
            candidates = gss.get_waiting_rooms(is_two_player, bet_int)

            for game_id in candidates:
                state = gss.get_state(game_id)

                # Lazy cleanup: state gone or wrong, remove from index
                if not state or state.get("is_private"):
                    gss.remove_waiting_room(game_id, is_two_player, bet_int)
                    continue

                if state.get("game_status") != "LOBBY":
                    gss.remove_waiting_room(game_id, is_two_player, bet_int)
                    continue

                if state.get("is_two_player_mode") != is_two_player:
                    gss.remove_waiting_room(game_id, is_two_player, bet_int)
                    continue

                if int(state.get("bet_amount", 0)) != bet_int:
                    gss.remove_waiting_room(game_id, is_two_player, bet_int)
                    continue

                if (
                    state.get("game_status") == "LOBBY"
                    and now - state.get("created_at", now) > 120
                    and len(state.get("player_assignments", {})) == 0
                ):
                    _cleanup_stale_lobby(game_id)
                    continue

                if player_token and player_token in state.get("player_assignments", {}):
                    continue

                if len(state.get("player_assignments", {})) < required_players:
                    return str(game_id)

            return None

    # Slow fallback: old behavior for callers without bet_amount
    for game_id, state in list(gss.iter_all_states()):

        if state.get("is_private"):
            continue

        if (
            state.get("game_status") == "LOBBY"
            and now - state.get("created_at", now) > 120
        ):
            _cleanup_stale_lobby(game_id)
            continue

        if state.get("is_two_player_mode") != is_two_player:
            continue

        if state.get("game_status") in (
            "COMPLETED", "CANCELLED", "ACTIVE",
        ):
            continue

        if bet_amount is not None:
            if int(state.get("bet_amount", 0)) != int(bet_amount):
                continue

        if player_token:
            if player_token in state.get("player_assignments", {}):
                logger.debug(
                    "SKIP room %s — player already in", game_id,
                )
                continue

        if len(state.get("player_assignments", {})) < required_players:
            return str(game_id)

    return None


def create_room(is_two_player=True, bet_amount=None):

    game_id = str(uuid.uuid4())

    state = get_or_create_game_state(
        game_id=game_id,
        is_two_player=is_two_player,
    )

    if bet_amount is not None:
        state["bet_amount"] = int(bet_amount)
        gss.set_state(game_id, state)

    # Note: NOT added to waiting set yet — added when first player joins
    return game_id, state


def initialize_game(
    player_token,
    player_name="Player",
    is_two_player=True,
    bet_amount=None,
):

    if not player_token:
        return {"status": "error", "message": "Player token is required."}

    if not player_name:
        player_name = "Player"

    profile = (
        UserProfileBalance.objects
        .filter(device_token=player_token)
        .first()
    )

    if not profile:
        return {
            "status": "error",
            "message": "User wallet profile not found.",
        }

    if bet_amount is not None and profile.coins < int(bet_amount):
        return {
            "status": "error",
            "message": (
                f"Insufficient funds. "
                f"Required: {format_dollar(bet_amount)}, "
                f"Available: {format_dollar(profile.coins)}."
            ),
        }

    # ==========================================================
    # ✅ Cleanup uses player_lobby index — O(1)
    # ==========================================================

    old_lobby_id = gss.get_player_lobby(player_token)

    if old_lobby_id:
        old_state = gss.get_state(old_lobby_id)
        if (
            old_state
            and old_state.get("game_status") == "LOBBY"
            and player_token in old_state.get("player_assignments", {})
        ):
            def _remove(state):
                if player_token in state.get("player_assignments", {}):
                    del state["player_assignments"][player_token]
                if player_token in state.get("player_names", {}):
                    del state["player_names"][player_token]
                if player_token in state.get("player_profiles", {}):
                    del state["player_profiles"][player_token]
                return len(state.get("player_assignments", {}))

            try:
                remaining = gss.mutate_game(old_lobby_id, _remove)
            except gss.LockTimeout:
                remaining = None

            if remaining is not None:
                logger.info(
                    "CLEANED stale LOBBY | Game=%s | Player=%s | Remaining=%s",
                    old_lobby_id,
                    player_token,
                    remaining,
                )

                if remaining == 0:
                    _cleanup_stale_lobby(old_lobby_id)

        gss.clear_player_lobby(player_token)

    # ==========================================================
    # Find or create room
    # ==========================================================

    game_id = find_waiting_room(
        is_two_player=is_two_player,
        player_token=player_token,
        bet_amount=bet_amount,
    )

    if game_id is None:
        for attempt in range(MATCHMAKING_RETRIES):
            time.sleep(MATCHMAKING_RETRY_DELAY)
            game_id = find_waiting_room(
                is_two_player=is_two_player,
                player_token=player_token,
                bet_amount=bet_amount,
            )
            if game_id is not None:
                logger.info(
                    "MATCHMAKING RETRY HIT | Game=%s | Attempt=%s",
                    game_id,
                    attempt + 1,
                )
                break

    if game_id is None:
        game_id, state = create_room(
            is_two_player=is_two_player,
            bet_amount=bet_amount,
        )
        logger.info(
            "ROOM CREATED | Game=%s | Mode=%s",
            game_id,
            "2P" if is_two_player else "4P",
        )
    else:
        state = gss.get_state(game_id)

    def _assign(state):
        color = assign_player_color(state, player_token)
        if color is None:
            return None

        state.setdefault("player_names", {})[player_token] = player_name

        pic_url = None
        if profile.profile_pic and hasattr(profile.profile_pic, 'url'):
            pic_url = profile.profile_pic.url

        state.setdefault("player_profiles", {})[player_token] = pic_url

        count = len(state["player_assignments"])
        required = 2 if is_two_player else 4
        if count >= required:
            state["game_status"] = "ACTIVE"
            state["status_text"] = "Game started!"
            state["turn_deadline"] = time.time() + 20
        else:
            state["game_status"] = "LOBBY"
            state["status_text"] = "Waiting for opponents..."

        return color, count

    try:
        res = gss.mutate_game(game_id, _assign)
    except gss.LockTimeout:
        return {
            "status": "error",
            "message": "Server busy. Try again.",
        }

    if res is None:
        return {
            "status": "full",
            "game_id": game_id,
            "message": "Room is full.",
        }

    assigned_color, player_count = res
    state = gss.get_state(game_id)
    required_players = 2 if is_two_player else 4

    # ==========================================================
    # Update waiting index based on new status
    # ==========================================================

    if state:
        bet_for_index = int(state.get("bet_amount", 0) or 0)

        if not state.get("is_private", False) and bet_for_index > 0:
            if state["game_status"] == "ACTIVE":
                # Game filled — remove from waiting set
                gss.remove_waiting_room(game_id, is_two_player, bet_for_index)
                # Clear player_lobby for ALL participants (they're active now)
                for tok in state.get("player_assignments", {}).keys():
                    gss.clear_player_lobby(tok)
            elif state["game_status"] == "LOBBY":
                # Still waiting — add/keep in set
                gss.add_waiting_room(game_id, is_two_player, bet_for_index)
                # Set player_lobby for current player
                gss.set_player_lobby(player_token, game_id)

    logger.info(
        "PLAYER JOINED | Game=%s | Color=%s | Count=%s/%s",
        game_id,
        assigned_color,
        player_count,
        required_players,
    )

    return {
        "status": "success",
        "game_id": game_id,
        "color": assigned_color,
        "game_status": state["game_status"],
        "player_count": player_count,
        "required_players": required_players,
        "player_names": state.get("player_names", {}),
        "player_profiles": state.get("player_profiles", {}),
    }


def delete_game_room(game_id):
    # ✅ Remove from waiting index before deleting state
    state = gss.get_state(game_id)
    if state:
        is_two = state.get("is_two_player_mode", True)
        bet = int(state.get("bet_amount", 0))
        if bet > 0 and not state.get("is_private", False):
            gss.remove_waiting_room(game_id, is_two, bet)
        for token in state.get("player_assignments", {}).keys():
            gss.clear_player_lobby(token)

    removed = gss.delete_state(game_id)

    if removed:
        logger.info("ROOM DELETED | Game=%s", game_id)
    else:
        logger.warning("ROOM DELETE | Game=%s | not found", game_id)

    return removed