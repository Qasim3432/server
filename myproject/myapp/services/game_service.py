# myapp/services/game_service.py

import uuid

from .game_state import (
    get_or_create_game_state,
    assign_player_color,
    remove_game_state,
)


# ==========================================================
# FIND WAITING ROOM
# ==========================================================

def find_waiting_room(is_two_player=True):
    """
    Find an existing room that is still accepting players.

    Returns:
        game_id
        or None if no suitable room exists.
    """

    from ..consumers import ACTIVE_GAMES

    required_players = (
        2 if is_two_player else 4
    )

    for game_id, state in list(ACTIVE_GAMES.items()):

        # --------------------------------------------------
        # Ignore rooms with different game mode
        # --------------------------------------------------

        if state.get(
            "is_two_player_mode"
        ) != is_two_player:
            continue

        # --------------------------------------------------
        # Ignore completed/cancelled rooms
        # --------------------------------------------------

        if state.get(
            "game_status"
        ) in (
            "COMPLETED",
            "CANCELLED",
        ):
            continue

        # --------------------------------------------------
        # Count players
        # --------------------------------------------------

        player_count = len(
            state.get(
                "player_assignments",
                {}
            )
        )

        # --------------------------------------------------
        # Room has space
        # --------------------------------------------------

        if player_count < required_players:

            return str(game_id)

    return None


# ==========================================================
# CREATE ROOM
# ==========================================================

def create_room(is_two_player=True):
    """
    Creates a completely new UUID room.
    """

    game_id = str(
        uuid.uuid4()
    )

    state = get_or_create_game_state(
        game_id=game_id,
        is_two_player=is_two_player,
    )

    return game_id, state


# ==========================================================
# JOIN MATCHMAKING
# ==========================================================

def initialize_game(
    player_token,
    is_two_player=True,
):
    """
    Find an existing waiting room or create a new one.

    Flow:

        1. Search for waiting room.
        2. If none exists -> create UUID room.
        3. Assign player color.
        4. Return room information.
    """

    # ------------------------------------------------------
    # Validate player
    # ------------------------------------------------------

    if not player_token:

        return {
            "status": "error",
            "message": "Player token is required.",
        }

    # ------------------------------------------------------
    # Find existing waiting room
    # ------------------------------------------------------

    game_id = find_waiting_room(
        is_two_player=is_two_player
    )

    # ------------------------------------------------------
    # No room -> create one
    # ------------------------------------------------------

    if game_id is None:

        game_id, state = create_room(
            is_two_player=is_two_player
        )

        print(
            f"🆕 ROOM CREATED | "
            f"Game={game_id} | "
            f"Mode={'2P' if is_two_player else '4P'}"
        )

    else:

        state = get_or_create_game_state(
            game_id=game_id,
            is_two_player=is_two_player,
        )

        print(
            f"🔎 ROOM FOUND | "
            f"Game={game_id}"
        )

    # ------------------------------------------------------
    # Assign player color
    # ------------------------------------------------------

    assigned_color = assign_player_color(
        state,
        player_token,
    )

    # ------------------------------------------------------
    # Room became full between lookup and assignment
    # ------------------------------------------------------

    if assigned_color is None:

        return {
            "status": "full",
            "game_id": game_id,
            "message": "Room is full.",
        }

    # ------------------------------------------------------
    # Determine player count
    # ------------------------------------------------------

    player_count = len(
        state.get(
            "player_assignments",
            {}
        )
    )

    required_players = (
        2 if is_two_player else 4
    )

    # ------------------------------------------------------
    # Activate game when full
    # ------------------------------------------------------

    if player_count >= required_players:

        state[
            "game_status"
        ] = "ACTIVE"

        state[
            "status_text"
        ] = "Game started!"

        print(
            f"🎮 GAME STARTED | "
            f"Game={game_id} | "
            f"Players={player_count}"
        )

    else:

        state[
            "game_status"
        ] = "LOBBY"

        state[
            "status_text"
        ] = (
            "Waiting for opponents..."
        )

    # ------------------------------------------------------
    # Return
    # ------------------------------------------------------

    return {
        "status": "success",
        "game_id": game_id,
        "color": assigned_color,
        "game_status": state[
            "game_status"
        ],
        "player_count": player_count,
        "required_players": required_players,
    }


# ==========================================================
# DELETE ROOM
# ==========================================================

def delete_game_room(game_id):
    """
    Permanently removes an in-memory game room.

    Call this after the game has successfully completed.
    """

    removed = remove_game_state(
        game_id
    )

    if removed:

        print(
            f"🗑️ ROOM DELETED | "
            f"Game={game_id}"
        )

    else:

        print(
            f"⚠️ ROOM DELETE REQUEST | "
            f"Game={game_id} | "
            f"Room not found"
        )

    return removed