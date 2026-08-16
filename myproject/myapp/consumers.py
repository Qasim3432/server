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


def get_global_cell_index(color, position):
    """
    Converts a player's local Ludo position to the
    global 52-cell board position.
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
        # Read player token from:
        #
        # ws://.../ws/ludo/1/?player_token=PLAYER_A
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

        self.player_token = (
            token_list[0]
            if token_list
            else "Unknown_Device"
        )

        # --------------------------------------------------
        # Join WebSocket group
        # --------------------------------------------------

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        await self.accept()

        print(
            f"▼ WS CONNECTED: "
            f"Game={self.game_id} "
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
            f"▲ WS DISCONNECTED: "
            f"Game={self.game_id} "
            f"Player={self.player_token}"
        )

    # ======================================================
    # TURN CHECK
    # ======================================================

    def is_current_players_turn(self, state):

        current_color = (
            state["player_turn_order"][
                state["turn_index"]
            ]
        )

        assigned_color = (
            state["player_assignments"]
            .get(self.player_token)
        )

        return current_color == assigned_color

    # ======================================================
    # FIND DEVICE BY COLOR
    # ======================================================

    def get_device_for_color(self, state, color):

        for (
            device_token,
            assigned_color
        ) in state["player_assignments"].items():

            if assigned_color == color:
                return device_token

        return None

    # ======================================================
    # WIN CONDITION
    # ======================================================

    def has_player_won(self, state, color):

        player_tokens = [
            token
            for token in state["tokens"]
            if token["color"] == color
        ]

        # A Ludo player has 4 tokens.
        #
        # Player wins when all 4 reach position 56.

        return (
            len(player_tokens) == 4
            and all(
                token["position"] == 56
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
    # HANDLE WINNER
    # ======================================================

    async def handle_game_winner(
        self,
        state,
        winning_color,
    ):

        # --------------------------------------------------
        # Find device token belonging to winning color
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
                "Winner detected, but "
                "player identity could not be found."
            )

            return

        # --------------------------------------------------
        # Execute atomic database payout
        # --------------------------------------------------

        result = await self.payout_winner(
            self.game_id,
            winning_device_token,
        )

        # --------------------------------------------------
        # Payout failed
        # --------------------------------------------------

        if not result["success"]:

            state["game_status"] = "PAYOUT_ERROR"

            state["status_text"] = (
                f"{winning_color} won, "
                f"but payout failed: "
                f"{result['message']}"
            )

            print(
                f"❌ PAYOUT FAILED: "
                f"Game={self.game_id} "
                f"Winner={winning_device_token} "
                f"Reason={result['message']}"
            )

            return

        # --------------------------------------------------
        # Payout succeeded
        # --------------------------------------------------

        state["winner"] = winning_color

        state["winner_device_token"] = (
            winning_device_token
        )

        state["game_status"] = "COMPLETED"

        state["winner_payout"] = (
            result["winner_payout"]
        )

        state["platform_fee"] = (
            result["service_fee"]
        )

        state["total_pool"] = (
            result["total_pool"]
        )

        state["status_text"] = (
            f"{winning_color} WON! "
            f"{result['winner_payout']} "
            f"coins awarded."
        )

        print(
            f"🏆 GAME WON: "
            f"Game={self.game_id} "
            f"Winner={winning_color} "
            f"Device={winning_device_token} "
            f"Payout={result['winner_payout']} "
            f"Fee={result['service_fee']}"
        )

    # ======================================================
    # RECEIVE WEBSOCKET MESSAGE
    # ======================================================

    async def receive(self, text_data):

        try:
            data = json.loads(text_data)

        except Exception:
            return

        action = data.get("action")

        state = ACTIVE_GAMES.get(
            self.game_id
        )

        if not state:
            return

        # --------------------------------------------------
        # Prevent actions after game completion
        # --------------------------------------------------

        if state.get("game_status") == "COMPLETED":

            await self.broadcast_current_state()

            return

        if state.get("game_status") == "PAYOUT_ERROR":

            await self.broadcast_current_state()

            return

        # ==================================================
        # ROLL DICE
        # ==================================================

        if action == "roll_dice":

            if not self.is_current_players_turn(state):

                print(
                    f"⚠️ REJECTED ROLL: "
                    f"{self.player_token}"
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
                    f"⚠️ REJECTED MOVE: "
                    f"{self.player_token}"
                )

                return

            await self.handle_token_movement(
                state,
                data.get("token_id"),
                data.get("color"),
            )

        # --------------------------------------------------
        # Broadcast new state
        # --------------------------------------------------

        await self.broadcast_current_state()

    # ======================================================
    # DICE ROLL
    # ======================================================

    async def handle_dice_roll(self, state):

        # Already rolled and waiting for movement
        if state["has_rolled"]:
            return

        roll = random.randint(1, 6)

        state["current_dice_value"] = roll

        state["has_rolled"] = True

        current_player = (
            state["player_turn_order"][
                state["turn_index"]
            ]
        )

        player_tokens = [
            token
            for token in state["tokens"]
            if token["color"] == current_player
        ]

        # --------------------------------------------------
        # Find legal moves
        # --------------------------------------------------

        valid_moves = 0

        for token in player_tokens:

            # Token in yard
            if (
                token["position"] == -1
                and roll == 6
            ):
                valid_moves += 1

            # Token already on board
            elif (
                0 <= token["position"] <= 55
                and token["position"] + roll <= 56
            ):
                valid_moves += 1

        # --------------------------------------------------
        # No valid moves
        # --------------------------------------------------

        if valid_moves == 0:

            state["has_rolled"] = False

            state["turn_index"] = (
                state["turn_index"] + 1
            ) % len(
                state["player_turn_order"]
            )

            next_player = (
                state["player_turn_order"][
                    state["turn_index"]
                ]
            )

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
        # Must have rolled first
        # --------------------------------------------------

        if not state["has_rolled"]:
            return

        current_player = (
            state["player_turn_order"][
                state["turn_index"]
            ]
        )

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
                for token in state["tokens"]
                if (
                    token["id"] == token_id
                    and token["color"] == color
                )
            ),
            None,
        )

        if not token:
            return

        roll = state["current_dice_value"]

        move_executed = False

        grant_bonus_roll = (
            roll == 6
        )

        # ==================================================
        # BASE YARD BREAKOUT
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
        # NORMAL TRACK MOVEMENT
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

                # ==========================================
                # COLLISION / KILL LOGIC
                # ==========================================

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

                    for enemy_token in state["tokens"]:

                        if (
                            enemy_token["color"]
                            != color
                            and enemy_token["position"]
                            >= 0
                        ):

                            enemy_global_cell = (
                                get_global_cell_index(
                                    enemy_token["color"],
                                    enemy_token["position"],
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
                                    f"out "
                                    f"{enemy_token['color']}! "
                                    f"Bonus roll granted."
                                )

        # ==================================================
        # INVALID MOVE
        # ==================================================

        if not move_executed:

            state["status_text"] = (
                f"Invalid move for that token! "
                f"{color}, select a different "
                f"valid token piece."
            )

            return

        # ==================================================
        # CLEAR ROLL
        # ==================================================

        state["has_rolled"] = False

        # ==================================================
        # WIN CHECK
        # ==================================================

        if self.has_player_won(
            state,
            color,
        ):

            # ----------------------------------------------
            # We have a winner.
            # ----------------------------------------------

            state["winner"] = color

            state["game_status"] = "WON"

            state["status_text"] = (
                f"{color} WON THE GAME! "
                f"Processing payout..."
            )

            # ----------------------------------------------
            # Process database payout
            # ----------------------------------------------

            await self.handle_game_winner(
                state,
                color,
            )

            # ----------------------------------------------
            # IMPORTANT:
            # Do not give another turn.
            # ----------------------------------------------

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
        # NORMAL TURN CHANGE
        # ==================================================

        if not grant_bonus_roll:

            state["turn_index"] = (
                state["turn_index"] + 1
            ) % len(
                state["player_turn_order"]
            )

            next_player = (
                state["player_turn_order"][
                    state["turn_index"]
                ]
            )

            state["status_text"] = (
                f"{next_player}'s Turn! "
                f"Tap the dice to roll."
            )

        else:

            # Same player gets another roll
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
    # SEND STATE TO SOCKET
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