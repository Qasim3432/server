# myapp/services/game_state.py

import time
from . import game_state_store as gss

def get_or_create_game_state(game_id, is_two_player=True):
    game_id = str(game_id)
    state = gss.get_state(game_id)
    if state is not None:
        return state

    player_turn_order = (
        ["BLUE", "GREEN"] if is_two_player
        else ["BLUE", "RED", "GREEN", "YELLOW"]
    )

    state = {
        "is_two_player_mode": is_two_player,
        "required_players": 2 if is_two_player else 4,
        "created_at": time.time(),
        "game_status": "LOBBY",
        "status_text": "Waiting for opponents...",
        "turn_index": 0,
        "player_turn_order": player_turn_order,
        "player_assignments": {},
        "player_names": {},
        "current_dice_value": 1,
        "has_rolled": False,
        "tokens": [],
        "surrendered_tokens": [],
    }
    
    for color in player_turn_order:
        for token_id in range(4):
            state["tokens"].append({
                "id": token_id, "color": color, "position": -1,
            })
            
    gss.set_state(game_id, state)
    return state

def assign_player_color(state, player_token):
    assignments = state["player_assignments"]
    if player_token in assignments:
        return assignments[player_token]

    full_order = (
        ["BLUE", "GREEN"] if state.get("is_two_player_mode")
        else ["BLUE", "RED", "GREEN", "YELLOW"]
    )
    
    assigned = set(assignments.values())
    for color in full_order:
        if color not in assigned:
            assignments[player_token] = color
            return color
            
    return None

def remove_game_state(game_id):
    return gss.delete_state(str(game_id))