import json
import random
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .services.wager_service import finalize_wager_game


# ==========================================================
# ACTIVE GAME MEMORY
# ==========================================================

ACTIVE_GAMES = {}


# ==========================================================
# TEST MODE
# ==========================================================
#
# IMPORTANT:
# Keep this True only while developing/testing.
#
# Set to False before releasing the production APK.
#
# ==========================================================

TEST_MODE = True


# ==========================================================
# LUDO BOARD CONFIGURATION
# ==========================================================

START_OFFSETS = {
    "BLUE": 0,
    "RED": 13,
    "GREEN": 26,
    "YELLOW": 39,
}


SAFE_GLOBAL_CELLS = {
    0,
    8,
    13,
    21,
    26,
    34,
    39,
    47,
}


# ==========================================================
# GLOBAL CELL CONVERSION
# ==========================================================

def get_global_cell_index(color, position):
    """
    Convert local player position to global 52-cell board.

    -1  = base
    0-50 = normal board
    51+ = home lane / finish
    """

    if position == -1 or position >= 51:
        return None

    return (
        START_OFFSETS[color] + position
    ) % 52


# ==========================================================
# LUDO WEBSOCKET CONSUMER
# ==========================================================

class LudoGameConsumer(AsyncWebsocketConsumer):

    # ======================================================
    # CONNECT
    # ======================================================

    async def connect(self):

        self.game_id = str(
            self.scope["url_route"]["kwargs"]["game_id"]
        )

        self.room_group_name = (
            f"ludo_match_{self.game_id}"
        )

        # --------------------------------------------------
        # Read player_token from query string
        #
        # /ws/ludo/1/?player_token=ABC
        # --------------------------------------------------

        query_string = (
            self.scope
            .get("query_string", b"")
            .decode("utf-8")
        )

        parsed_params = parse_qs(query_string)

        token_list = parsed_params.get(
            "player_token",
            []
        )

        if token_list:
            self.player_token = token_list[0]
        else:
            self.player_token = "Unknown_Device"

        # --------------------------------------------------
        # Join channel group
        # --------------------------------------------------

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        await self.accept()

        print(
            f"▼ WS CONNECTED | "
            f"Game={self.game_id} | "
            f"Player={self.player_token}"
        )

        # --------------------------------------------------
        # Send current state
        # --------------------------------------------------

        await self.broadcast_current_state()

    # ======================================================
    # DISCONNECT
    # ======================================================

    async def disconnect(self, close_code):

        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name,
        )

        print(
            f"▲ WS DISCONNECTED | "
            f"Game={getattr(self, 'game_id', '?')} | "
            f"Player={getattr(self, 'player_token', '?')} | "
            f"Code={close_code}"
        )

    # ======================================================
    # TURN CHECK
    # ======================================================

    def is_current_players_turn(self, state):

        turn_order = state.get(
            "player_turn_order",
            []
        )

        if not turn_order:
            return False

        turn_index = state.get(
            "turn_index",
            0
        )

        if turn_index >= len(turn_order):
            return False

        current_color = turn_order[turn_index]

        assigned_color = (
            state.get("player_assignments", {})
            .get(self.player_token)
        )

        return current_color == assigned_color

    # ======================================================
    # FIND DEVICE BY COLOR
    # ======================================================

    def get_device_for_color(self, state, color):

        assignments = state.get(
            "player_assignments",
            {}
        )

        for device_token, assigned_color in assignments.items():

            if assigned_color == color:
                return device_token

        return None

    # ======================================================
    # WIN CONDITION
    # ======================================================

    def has_player_won(self, state, color):

        player_tokens = [
            token
            for token in state.get("tokens", [])
            if token.get("color") == color
        ]

        # Exactly four tokens must exist
        # and all four must reach position 56.

        return (
            len(player_tokens) == 4
            and all(
                token.get("position") == 56
                for token in player_tokens
            )
        )

    # ======================================================
    # DATABASE PAYOUT
    # ======================================================

    @database_sync_to_async
    def payout_winner(
        self,
        game_id,
        winning_device_token,
    ):

        return finalize_wager_game(
            game_id=game_id,
            winning_device_token=winning_device_token,
        )

    # ======================================================
    # HANDLE GAME WINNER
    # ======================================================

    async def handle_game_winner(
        self,
        state,
        winning_color,
    ):

        # --------------------------------------------------
        # Find winning device
        # --------------------------------------------------

        winning_device_token = (
            self.get_device_for_color(
                state,
                winning_color,
            )
        )

        if not winning_device_token:

            state["game_status"] = "PAYOUT_ERROR"

            state["status_text"] = (
                "Winner detected, but player identity "
                "could not be found."
            )

            print(
                f"❌ PAYOUT ERROR | "
                f"Game={self.game_id} | "
                f"Winner={winning_color} | "
                f"Device not found"
            )

            return

        # --------------------------------------------------
        # Execute atomic database payout
        # --------------------------------------------------

        try:

            result = await self.payout_winner(
                self.game_id,
                winning_device_token,
            )

        except Exception as e:

            state["game_status"] = "PAYOUT_ERROR"

            state["status_text"] = (
                "Winner detected, but an internal "
                "payout error occurred."
            )

            print(
                f"❌ PAYOUT EXCEPTION | "
                f"Game={self.game_id} | "
                f"Winner={winning_device_token} | "
                f"Error={e}"
            )

            return

        # --------------------------------------------------
        # IMPORTANT
        #
        # finalize_wager_game() returns:
        #
        # {
        #     "status": "success",
        #     ...
        # }
        #
        # NOT:
        #
        # {
        #     "success": True
        # }
        # --------------------------------------------------

        payout_success = (
            isinstance(result, dict)
            and result.get("status") == "success"
        )

        # --------------------------------------------------
        # PAYOUT FAILED
        # --------------------------------------------------

        if not payout_success:

            state["game_status"] = "PAYOUT_ERROR"

            if isinstance(result, dict):

                error_message = result.get(
                    "message",
                    "Unknown payout error.",
                )

            else:

                error_message = (
                    "Invalid payout response."
                )

            state["status_text"] = (
                f"{winning_color} won, "
                f"but payout failed: "
                f"{error_message}"
            )

            print(
                f"❌ PAYOUT FAILED | "
                f"Game={self.game_id} | "
                f"Winner={winning_device_token} | "
                f"Reason={error_message}"
            )

            return

        # --------------------------------------------------
        # PAYOUT SUCCESS
        # --------------------------------------------------

        state["winner"] = winning_color

        state["winner_device_token"] = (
            winning_device_token
        )

        state["game_status"] = "COMPLETED"

        state["winner_payout"] = int(
            result.get(
                "winner_payout",
                0,
            )
        )

        state["platform_fee"] = int(
            result.get(
                "service_fee",
                0,
            )
        )

        state["total_pool"] = int(
            result.get(
                "total_pool",
                0,
            )
        )

        state["has_rolled"] = False

        state["status_text"] = (
            f"{winning_color} WON! "
            f"{state['winner_payout']} "
            f"coins awarded."
        )

        print(
            f"🏆 GAME WON | "
            f"Game={self.game_id} | "
            f"Winner={winning_color} | "
            f"Device={winning_device_token} | "
            f"Payout={state['winner_payout']} | "
            f"Fee={state['platform_fee']}"
        )

    # ======================================================
    # RECEIVE WEBSOCKET MESSAGE
    # ======================================================

    async def receive(self, text_data):

        # --------------------------------------------------
        # Parse JSON
        # --------------------------------------------------

        try:

            data = json.loads(text_data)

        except (json.JSONDecodeError, TypeError):

            print(
                f"⚠️ INVALID JSON | "
                f"Game={self.game_id} | "
                f"Player={self.player_token}"
            )

            return

        action = data.get("action")

        # --------------------------------------------------
        # Get active state
        # --------------------------------------------------

        state = ACTIVE_GAMES.get(
            self.game_id
        )

        if not state:

            print(
                f"⚠️ GAME STATE NOT FOUND | "
                f"Game={self.game_id}"
            )

            return

        # ==================================================
        # TEST FINISH BLUE
        # ==================================================
        #
        # This branch MUST be inside receive().
        #
        # It moves all four BLUE tokens to 56.
        #
        # Then it calls the EXACT SAME winner/payout
        # logic used by the real game.
        #
        # ==================================================

        if action == "test_finish_blue":

            if not TEST_MODE:

                print(
                    f"⚠️ TEST ACTION BLOCKED | "
                    f"Game={self.game_id} | "
                    f"Player={self.player_token}"
                )

                state["status_text"] = (
                    "Testing controls are disabled."
                )

                await self.broadcast_current_state()

                return

            # --------------------------------------------------
            # Do not test an already completed game
            # --------------------------------------------------

            if state.get("game_status") in (
                "COMPLETED",
                "PAYOUT_ERROR",
            ):

                state["status_text"] = (
                    "Game has already finished."
                )

                await self.broadcast_current_state()

                return

            print(
                f"🧪 TEST FINISH BLUE | "
                f"Game={self.game_id} | "
                f"RequestedBy={self.player_token}"
            )

            # --------------------------------------------------
            # Find BLUE tokens
            # --------------------------------------------------

            blue_tokens = [
                token
                for token in state.get("tokens", [])
                if token.get("color") == "BLUE"
            ]

            # --------------------------------------------------
            # Validate four BLUE tokens
            # --------------------------------------------------

            if len(blue_tokens) != 4:

                state["status_text"] = (
                    "TEST ERROR: BLUE does not "
                    "have exactly 4 tokens."
                )

                print(
                    f"❌ TEST FINISH FAILED | "
                    f"Game={self.game_id} | "
                    f"BlueTokens={len(blue_tokens)}"
                )

                await self.broadcast_current_state()

                return

            # --------------------------------------------------
            # Move ALL BLUE tokens to position 56
            # --------------------------------------------------

            for token in blue_tokens:

                token["position"] = 56

            # --------------------------------------------------
            # Force BLUE winner
            # --------------------------------------------------

            state["winner"] = "BLUE"

            state["game_status"] = "WON"

            state["has_rolled"] = False

            state["status_text"] = (
                "BLUE test finish triggered. "
                "Processing payout..."
            )

            # --------------------------------------------------
            # Use normal payout path
            # --------------------------------------------------

            await self.handle_game_winner(
                state,
                "BLUE",
            )

            # --------------------------------------------------
            # Broadcast final result
            # --------------------------------------------------

            await self.broadcast_current_state()

            return

        # ==================================================
        # BLOCK NORMAL ACTIONS AFTER COMPLETION
        # ==================================================

        if state.get("game_status") in (
            "COMPLETED",
            "PAYOUT_ERROR",
        ):

            await self.broadcast_current_state()

            return

        # ==================================================
        # ROLL DICE
        # ==================================================

        if action == "roll_dice":

            if not self.is_current_players_turn(state):

                print(
                    f"⚠️ REJECTED ROLL | "
                    f"Game={self.game_id} | "
                    f"Player={self.player_token}"
                )

                return

            await self.handle_dice_roll(
                state
            )

        # ==================================================
        # MOVE TOKEN
        # ==================================================

        elif action == "move_token":

            if not self.is_current_players_turn(state):

                print(
                    f"⚠️ REJECTED MOVE | "
                    f"Game={self.game_id} | "
                    f"Player={self.player_token}"
                )

                return

            await self.handle_token_movement(
                state,
                data.get("token_id"),
                data.get("color"),
            )

        # ==================================================
        # UNKNOWN ACTION
        # ==================================================

        else:

            print(
                f"⚠️ UNKNOWN ACTION | "
                f"Game={self.game_id} | "
                f"Player={self.player_token} | "
                f"Action={action}"
            )

            return

        # --------------------------------------------------
        # Broadcast new state
        # --------------------------------------------------

        await self.broadcast_current_state()

    # ======================================================
    # DICE ROLL
    # ======================================================

    async def handle_dice_roll(self, state):

        # --------------------------------------------------
        # Already rolled
        # --------------------------------------------------

        if state.get("has_rolled"):

            return

        # --------------------------------------------------
        # Validate turn
        # --------------------------------------------------

        turn_order = state.get(
            "player_turn_order",
            []
        )

        if not turn_order:

            return

        turn_index = state.get(
            "turn_index",
            0
        )

        if turn_index >= len(turn_order):

            return

        current_player = turn_order[
            turn_index
        ]

        # --------------------------------------------------
        # Roll
        # --------------------------------------------------

        roll = random.randint(
            1,
            6,
        )

        state["current_dice_value"] = roll

        state["has_rolled"] = True

        player_tokens = [
            token
            for token in state.get("tokens", [])
            if token.get("color") == current_player
        ]

        # --------------------------------------------------
        # Find legal moves
        # --------------------------------------------------

        valid_moves = 0

        for token in player_tokens:

            position = token.get(
                "position",
                -1,
            )

            # Base token requires 6
            if (
                position == -1
                and roll == 6
            ):

                valid_moves += 1

            # Normal board
            elif (
                0 <= position <= 55
                and position + roll <= 56
            ):

                valid_moves += 1

        # --------------------------------------------------
        # No moves
        # --------------------------------------------------

        if valid_moves == 0:

            state["has_rolled"] = False

            state["turn_index"] = (
                state["turn_index"] + 1
            ) % len(turn_order)

            next_player = turn_order[
                state["turn_index"]
            ]

            state["status_text"] = (
                f"{current_player} rolled "
                f"{roll} (No Moves)! "
                f"Pass to {next_player}."
            )

        else:

            state["status_text"] = (
                f"{current_player} rolled "
                f"{roll}! Select your token."
            )

    # ======================================================
    # TOKEN MOVEMENT
    # ======================================================

    async def handle_token_movement(
        self,
        state,
        token_id,
        color,
    ):

        # --------------------------------------------------
        # Must roll first
        # --------------------------------------------------

        if not state.get("has_rolled"):

            return

        # --------------------------------------------------
        # Current player
        # --------------------------------------------------

        turn_order = state.get(
            "player_turn_order",
            []
        )

        if not turn_order:

            return

        turn_index = state.get(
            "turn_index",
            0,
        )

        current_player = turn_order[
            turn_index
        ]

        # --------------------------------------------------
        # Color verification
        # --------------------------------------------------

        if color != current_player:

            state["status_text"] = (
                f"It is not {color}'s turn! "
                f"It is {current_player}'s turn."
            )

            return

        # --------------------------------------------------
        # Find token
        # --------------------------------------------------

        token = next(
            (
                token
                for token in state.get("tokens", [])
                if (
                    token.get("id") == token_id
                    and token.get("color") == color
                )
            ),
            None,
        )

        if token is None:

            state["status_text"] = (
                "Token not found."
            )

            return

        roll = int(
            state.get(
                "current_dice_value",
                0,
            )
        )

        move_executed = False

        # Six = bonus
        grant_bonus_roll = (
            roll == 6
        )

        # ==================================================
        # BASE -> START
        # ==================================================

        if (
            token["position"] == -1
            and roll == 6
        ):

            token["position"] = 0

            move_executed = True

            state["status_text"] = (
                f"{color} moved a token "
                f"out of the base!"
            )

        # ==================================================
        # NORMAL MOVEMENT
        # ==================================================

        elif 0 <= token["position"] <= 55:

            target_destination = (
                token["position"] + roll
            )

            if target_destination <= 56:

                token["position"] = (
                    target_destination
                )

                move_executed = True

                state["status_text"] = (
                    f"{color} moved a token "
                    f"forward by {roll}."
                )

                # ------------------------------------------
                # Collision detection
                # ------------------------------------------

                target_global_cell = (
                    get_global_cell_index(
                        color,
                        target_destination,
                    )
                )

                if (
                    target_global_cell is not None
                    and target_global_cell
                    not in SAFE_GLOBAL_CELLS
                ):

                    for enemy_token in state.get(
                        "tokens",
                        []
                    ):

                        if (
                            enemy_token.get("color")
                            != color
                            and enemy_token.get(
                                "position",
                                -1,
                            ) >= 0
                        ):

                            enemy_global_cell = (
                                get_global_cell_index(
                                    enemy_token.get(
                                        "color"
                                    ),
                                    enemy_token.get(
                                        "position"
                                    ),
                                )
                            )

                            if (
                                enemy_global_cell
                                == target_global_cell
                            ):

                                enemy_token[
                                    "position"
                                ] = -1

                                grant_bonus_roll = True

                                state[
                                    "status_text"
                                ] = (
                                    f"{color} kicked "
                                    f"{enemy_token['color']}! "
                                    f"Bonus roll granted."
                                )

        # ==================================================
        # INVALID MOVE
        # ==================================================

        if not move_executed:

            state["status_text"] = (
                f"Invalid move for that token! "
                f"{color}, select a valid token."
            )

            return

        # ==================================================
        # CLEAR DICE STATE
        # ==================================================

        state["has_rolled"] = False

        # ==================================================
        # CHECK WIN
        # ==================================================

        if self.has_player_won(
            state,
            color,
        ):

            state["winner"] = color

            state["game_status"] = "WON"

            state["status_text"] = (
                f"{color} WON THE GAME! "
                f"Processing payout..."
            )

            # ------------------------------------------
            # Real payout
            # ------------------------------------------

            await self.handle_game_winner(
                state,
                color,
            )

            return

        # ==================================================
        # TOKEN REACHED HOME
        # ==================================================

        if token["position"] == 56:

            grant_bonus_roll = True

            state["status_text"] = (
                f"{color} reached the goal! "
                f"Bonus roll granted."
            )

        # ==================================================
        # NEXT TURN
        # ==================================================

        if not grant_bonus_roll:

            state["turn_index"] = (
                state["turn_index"] + 1
            ) % len(turn_order)

            next_player = turn_order[
                state["turn_index"]
            ]

            state["status_text"] = (
                f"{next_player}'s Turn! "
                f"Tap the dice to roll."
            )

        else:

            state["status_text"] = (
                f"{color}'s Bonus Roll! "
                f"Tap the dice."
            )

    # ======================================================
    # BROADCAST GAME STATE
    # ======================================================

    async def broadcast_current_state(self):

        state = ACTIVE_GAMES.get(
            self.game_id
        )

        if not state:

            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "send_state_payload",
                "payload": state,
            },
        )

    # ======================================================
    # SEND STATE TO CLIENT
    # ======================================================

    async def send_state_payload(
        self,
        event,
    ):

        await self.send(
            text_data=json.dumps(
                {
                    "status": "success",
                    "game_state": event[
                        "payload"
                    ],
                }
            )
        )