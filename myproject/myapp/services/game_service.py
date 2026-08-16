from .game_state import (
    get_or_create_game_state,
    assign_player_color,
)


DEFAULT_GAME_ID = "1"


def initialize_game(player_token, is_two_player=True):
    """
    Initialize the lobby game and assign a player color.
    """

    game_id = DEFAULT_GAME_ID

    state = get_or_create_game_state(
        game_id=game_id,
        is_two_player=is_two_player,
    )

    assigned_color = assign_player_color(
        state,
        player_token,
    )

    if assigned_color is None:
        return {
            "status": "full",
            "game_id": game_id,
        }

    return {
        "status": "success",
        "game_id": int(game_id),
        "color": assigned_color,
    }