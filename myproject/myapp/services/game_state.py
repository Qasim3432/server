# myapp/services/game_state.py

from ..consumers import ACTIVE_GAMES


# ==========================================================
# CREATE / GET GAME STATE
# ==========================================================

def get_or_create_game_state(
    game_id,
    is_two_player=True,
):
    """
    Get an existing in-memory game state.

    If the room does not exist, create it.
    """

    game_id = str(game_id)

    if game_id not in ACTIVE_GAMES:

        player_turn_order = (
            ["BLUE", "GREEN"]
            if is_two_player
            else [
                "BLUE",
                "RED",
                "GREEN",
                "YELLOW",
            ]
        )

        ACTIVE_GAMES[game_id] = {

            # ------------------------------------------------
            # GAME CONFIG
            # ------------------------------------------------

            "is_two_player_mode":
                is_two_player,

            "required_players":
                2 if is_two_player else 4,

            # ------------------------------------------------
            # GAME STATUS
            # ------------------------------------------------

            "game_status":
                "LOBBY",

            "status_text":
                "Waiting for opponents...",

            # ------------------------------------------------
            # TURN
            # ------------------------------------------------

            "turn_index":
                0,

            "player_turn_order":
                player_turn_order,

            # ------------------------------------------------
            # PLAYERS
            # ------------------------------------------------

            "player_assignments":
                {},

            # ------------------------------------------------
            # DICE
            # ------------------------------------------------

            "current_dice_value":
                1,

            "has_rolled":
                False,

            # ------------------------------------------------
            # BOARD
            # ------------------------------------------------

            "tokens":
                [],
        }

        # ----------------------------------------------------
        # Create tokens
        # ----------------------------------------------------

        for color in player_turn_order:

            for token_id in range(4):

                ACTIVE_GAMES[
                    game_id
                ]["tokens"].append({

                    "id":
                        token_id,

                    "color":
                        color,

                    "position":
                        -1,
                })

        print(
            f"🆕 GAME STATE CREATED | "
            f"Game={game_id}"
        )

    return ACTIVE_GAMES[game_id]


# ==========================================================
# ASSIGN PLAYER COLOR
# ==========================================================

def assign_player_color(
    state,
    player_token,
):
    """
    Assign the first available color to the player.
    """

    assignments = state[
        "player_assignments"
    ]

    # ------------------------------------------------------
    # Player already joined
    # ------------------------------------------------------

    if player_token in assignments:

        return assignments[
            player_token
        ]

    # ------------------------------------------------------
    # Find available color
    # ------------------------------------------------------

    assigned_colors = set(
        assignments.values()
    )

    for color in state[
        "player_turn_order"
    ]:

        if color not in assigned_colors:

            assignments[
                player_token
            ] = color

            print(
                f"👤 PLAYER JOINED | "
                f"Color={color}"
            )

            return color

    # ------------------------------------------------------
    # Room full
    # ------------------------------------------------------

    return None


# ==========================================================
# REMOVE GAME STATE
# ==========================================================

def remove_game_state(
    game_id
):
    """
    Remove an in-memory game room.
    """

    game_id = str(game_id)

    if game_id in ACTIVE_GAMES:

        del ACTIVE_GAMES[
            game_id
        ]

        return True

    return False