from ..consumers import ACTIVE_GAMES


def get_or_create_game_state(game_id, is_two_player=True):
    """
    Get an existing in-memory game state or initialize a new one.
    """

    if game_id not in ACTIVE_GAMES:
        player_turn_order = (
            ["BLUE", "GREEN"]
            if is_two_player
            else ["BLUE", "RED", "GREEN", "YELLOW"]
        )

        ACTIVE_GAMES[game_id] = {
            "is_two_player_mode": is_two_player,
            "turn_index": 0,
            "player_turn_order": player_turn_order,
            "player_assignments": {},
            "current_dice_value": 1,
            "has_rolled": False,
            "status_text": "Waiting for opponents...",
            "tokens": [],
        }

        for color in player_turn_order:
            for token_id in range(4):
                ACTIVE_GAMES[game_id]["tokens"].append({
                    "id": token_id,
                    "color": color,
                    "position": -1,
                })

    return ACTIVE_GAMES[game_id]


def assign_player_color(state, player_token):
    """
    Assign the next available color to a player.
    """

    if player_token in state["player_assignments"]:
        return state["player_assignments"][player_token]

    assigned_colors = state["player_assignments"].values()

    for color in state["player_turn_order"]:
        if color not in assigned_colors:
            state["player_assignments"][player_token] = color
            return color

    return None