# myapp/consumers.py

import json
import logging
import asyncio
import random
import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .services import game_state_store as gss
from .services.wager_service import finalize_wager_game, cancel_wager

logger = logging.getLogger("myapp.consumers")

ACTIVE_GAMES = gss.ACTIVE_GAMES

PENDING_SURRENDER_TASKS = {}
PENDING_TURN_TIMERS = {}

AUTO_SURRENDER_GRACE_SECONDS = 30
TURN_TIMEOUT_SECONDS = 15

START_OFFSETS = {"BLUE": 0, "RED": 13, "GREEN": 26, "YELLOW": 39}
SAFE_GLOBAL_CELLS = {0, 8, 13, 21, 26, 34, 39, 47}


# ==========================================================
# HELPERS
# ==========================================================

def get_global_cell_index(color, position):
    if position == -1 or position >= 51:
        return None
    return (START_OFFSETS[color] + position) % 52


def _remove_player_from_state(state, leaver_token):
    leaver_color = state["player_assignments"].pop(leaver_token, None)

    # ✅ FIX — Keep names and profiles in state even after surrender
    # so REMATCH REQUEST can still look up the name.

    surrendered = state.setdefault("surrendered_tokens", [])
    if leaver_token not in surrendered:
        surrendered.append(leaver_token)

    if leaver_color:
        surrendered_colors = state.setdefault("surrendered_colors", [])
        if leaver_color not in surrendered_colors:
            surrendered_colors.append(leaver_color)

    if leaver_color:
        for token in state["tokens"]:
            if token["color"] == leaver_color:
                token["position"] = -1

    return leaver_color, list(state["player_assignments"].items())


def _cancel_turn_timer(game_id):
    game_key = str(game_id)
    task = PENDING_TURN_TIMERS.pop(game_key, None)
    if task is not None:
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if task is not current:
            task.cancel()
    try:
        gss.clear_turn_deadline(game_key)
    except Exception:
        logger.exception("clear_turn_deadline failed")


def _ensure_turn_loop(game_id, channel_layer):
    """
    Ensure exactly ONE poll loop per game is running.
    """
    game_key = str(game_id)

    existing = PENDING_TURN_TIMERS.get(game_key)
    if existing and not existing.done():
        logger.debug(
            "TURN_LOOP EXISTS | Game=%s | task_id=%s",
            game_key, id(existing),
        )
        return

    try:
        state = gss.get_state(game_key)
    except Exception:
        logger.exception("ensure_turn_loop get_state failed")
        return

    if not state or state.get("game_status") != "ACTIVE":
        logger.debug(
            "TURN_LOOP SKIP (not ACTIVE) | Game=%s | status=%s",
            game_key,
            state.get("game_status") if state else None,
        )
        return

    task = asyncio.create_task(_turn_loop(game_key, channel_layer))
    PENDING_TURN_TIMERS[game_key] = task

    logger.info(
        "TURN_LOOP START | Game=%s | task_id=%s",
        game_key, id(task),
    )


async def _turn_loop(game_id, channel_layer):
    """
    Persistent poll loop. Wakes every 1 second.
    """
    logger.info(
        "TURN_LOOP RUNNING | Game=%s | task_id=%s",
        game_id, id(asyncio.current_task()),
    )

    try:
        while True:

            await asyncio.sleep(1)

            try:
                state = await database_sync_to_async(gss.get_state)(game_id)
            except Exception:
                logger.exception("turn_loop get_state failed")
                continue

            if not state:
                logger.info("TURN_LOOP EXIT (no state) | Game=%s", game_id)
                PENDING_TURN_TIMERS.pop(game_id, None)
                return

            status = state.get("game_status")

            if status in ("COMPLETED", "CANCELLED", "PAYOUT_ERROR"):
                logger.info(
                    "TURN_LOOP EXIT (%s) | Game=%s",
                    status, game_id,
                )
                PENDING_TURN_TIMERS.pop(game_id, None)
                return

            if status != "ACTIVE":
                continue

            deadline = float(state.get("turn_deadline", 0) or 0)

            if time.time() < deadline:
                continue

            logger.info(
                "TURN_LOOP FIRE | Game=%s | deadline=%.1f now=%.1f",
                game_id, deadline, time.time(),
            )

            def _advance(st):
                if st.get("game_status") != "ACTIVE":
                    return None
                if time.time() < float(st.get("turn_deadline", 0) or 0):
                    return None
                order = st.get("player_turn_order", [])
                if not order:
                    return None
                st["has_rolled"] = False
                st["turn_index"] = (st["turn_index"] + 1) % len(order)
                next_color = order[st["turn_index"]]
                st["turn_deadline"] = time.time() + TURN_TIMEOUT_SECONDS
                st["status_text"] = f"⏰ Time out! {next_color}'s Turn"
                return next_color

            try:
                next_color = await database_sync_to_async(gss.mutate_game)(
                    game_id, _advance
                )
            except gss.LockTimeout:
                logger.warning(
                    "TURN_LOOP LOCK TIMEOUT | Game=%s", game_id,
                )
                continue
            except Exception:
                logger.exception("turn_loop advance failed for %s", game_id)
                continue

            if next_color is None:
                continue

            logger.info(
                "TURN TIMEOUT | Game=%s | Next=%s", game_id, next_color
            )

            new_state = await database_sync_to_async(gss.get_state)(game_id)

            if new_state:
                await channel_layer.group_send(
                    f"ludo_match_{game_id}",
                    {"type": "send_state_payload", "payload": new_state},
                )

    except asyncio.CancelledError:
        logger.info("TURN_LOOP CANCELLED | Game=%s", game_id)
        PENDING_TURN_TIMERS.pop(game_id, None)
        raise


# ==========================================================
# SURENDER AUTO TASK
# ==========================================================

@database_sync_to_async
def _ensure_game_room_exists(game_id, state):
    from .models import GameRoom, UserProfileBalance
    game = GameRoom.objects.filter(game_id=game_id).first()
    if game:
        return game
    assignments = state.get("player_assignments", {})
    bet_amount = int(state.get("bet_amount", 0))
    game = GameRoom.objects.create(
        game_id=game_id,
        bet_amount=bet_amount,
        game_status="ACTIVE",
        total_pool_escrow=(bet_amount * len(assignments)),
    )
    for device_token in assignments.keys():
        profile = UserProfileBalance.objects.filter(
            device_token=device_token
        ).first()
        if profile:
            game.players.add(profile)
    return game


async def _auto_surrender_task(game_id, leaver_token, channel_layer):
    try:
        await asyncio.sleep(AUTO_SURRENDER_GRACE_SECONDS)
    except asyncio.CancelledError:
        logger.info(
            "AUTO-SURRENDER CANCELLED | Game=%s | Player=%s",
            game_id,
            leaver_token,
        )
        return

    def _run(state):
        if not state:
            return None
        if state.get("game_status") in (
            "COMPLETED", "CANCELLED", "PAYOUT_ERROR",
        ):
            return None
        if leaver_token not in state.get("player_assignments", {}):
            return None
        return state.get("game_status")

    try:
        status = await database_sync_to_async(gss.mutate_game)(game_id, _run)
    except gss.LockTimeout:
        return
    if status is None:
        return

    def _surrender_mutate(state):
        st = state.get("game_status")
        if st == "LOBBY":
            return "LOBBY"
        leaver_color, remaining = _remove_player_from_state(
            state, leaver_token
        )
        state["status_text"] = (
            f"{leaver_color} disconnected. "
            + (
                "Game cancelled."
                if not remaining
                else (
                    "Winner determined."
                    if len(remaining) == 1
                    else "Game continues."
                )
            )
        )
        return ("ACTIVE", leaver_color, remaining)

    try:
        result = await database_sync_to_async(gss.mutate_game)(
            game_id, _surrender_mutate
        )
    except gss.LockTimeout:
        return

    if not result:
        return

    if result == "LOBBY":
        await database_sync_to_async(cancel_wager)(game_id)

        def _mark_cancelled(s):
            s["game_status"] = "CANCELLED"
            s["status_text"] = "Player abandoned room. Game cancelled."
            return s

        state = await database_sync_to_async(gss.mutate_game)(
            game_id, _mark_cancelled
        )
        _cancel_turn_timer(game_id)
        if state:
            await channel_layer.group_send(
                f"ludo_match_{game_id}",
                {"type": "send_state_payload", "payload": state},
            )
        return

    _, leaver_color, remaining = result
    state = await database_sync_to_async(gss.get_state)(game_id)
    if not state:
        return

    if not remaining:
        await database_sync_to_async(cancel_wager)(game_id)
        state["game_status"] = "CANCELLED"
        state["status_text"] = "All players disconnected. Game cancelled."
        await database_sync_to_async(gss.set_state)(game_id, state)
        _cancel_turn_timer(game_id)

    elif len(remaining) == 1:
        winner_token, winner_color = remaining[0]
        await _ensure_game_room_exists(game_id, state)
        pay_result = await database_sync_to_async(finalize_wager_game)(
            game_id=game_id,
            winning_device_token=winner_token,
            surrendered_tokens=state.get("surrendered_tokens", []),
        )
        if pay_result.get("status") == "success":
            state["winner"] = winner_color
            state["winner_device_token"] = winner_token
            state["game_status"] = "COMPLETED"
            state["winner_payout"] = int(pay_result.get("winner_payout", 0))
            state["status_text"] = (
                f"{winner_color} WON! {state['winner_payout']} coins awarded."
            )
        else:
            state["game_status"] = "PAYOUT_ERROR"
            state["status_text"] = (
                f"Payout failed: {pay_result.get('message', '?')}"
            )
        await database_sync_to_async(gss.set_state)(game_id, state)
        _cancel_turn_timer(game_id)

    else:
        await database_sync_to_async(gss.set_state)(game_id, state)
        _ensure_turn_loop(game_id, channel_layer)

    await channel_layer.group_send(
        f"ludo_match_{game_id}",
        {"type": "send_state_payload", "payload": state},
    )


# ==========================================================
# CONSUMER
# ==========================================================

class LudoGameConsumer(AsyncWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.accepted = False

    async def connect(self):
        self.game_id = str(self.scope["url_route"]["kwargs"]["game_id"])
        self.room_group_name = f"ludo_match_{self.game_id}"
        query_string = self.scope.get("query_string", b"").decode("utf-8")
        parsed_params = parse_qs(query_string)
        token_list = parsed_params.get("player_token", [])
        self.player_token = token_list[0] if token_list else None

        if not self.player_token:
            logger.warning("WS REJECTED | No token | Game=%s", self.game_id)
            await self.close(code=4001)
            return

        if not await self._validate_player_token(self.player_token):
            logger.warning(
                "WS REJECTED | Unknown token=%s | Game=%s",
                self.player_token,
                self.game_id,
            )
            await self.close(code=4001)
            return

        if not await self._player_in_game(self.game_id, self.player_token):
            logger.warning(
                "WS REJECTED | Player not in game OR wager not locked | "
                "Game=%s Player=%s — Client must call /api/wager/join/ first",
                self.game_id,
                self.player_token,
            )
            await self.close(code=4003)
            return

        task_key = f"{self.game_id}:{self.player_token}"
        existing = PENDING_SURRENDER_TASKS.pop(task_key, None)
        if existing:
            existing.cancel()
            logger.info(
                "Cancelled pending auto-surrender | Game=%s | Player=%s",
                self.game_id,
                self.player_token,
            )

        await self.channel_layer.group_add(
            self.room_group_name, self.channel_name
        )
        await self.accept()

        self.accepted = True

        await database_sync_to_async(gss.mark_player_back)(
            self.game_id, self.player_token
        )
        logger.info(
            "WS CONNECTED | Game=%s | Player=%s",
            self.game_id,
            self.player_token,
        )
        await self.broadcast_current_state()

    @database_sync_to_async
    def _validate_player_token(self, token):
        from .models import UserProfileBalance
        return UserProfileBalance.objects.filter(device_token=token).exists()

    @database_sync_to_async
    def _player_in_game(self, game_id, token):
        from .models import GameRoom
        return GameRoom.objects.filter(
            game_id=game_id, players__device_token=token
        ).exists()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name, self.channel_name
        )
        logger.info(
            "WS DISCONNECTED | Game=%s | Player=%s | code=%s",
            self.game_id,
            self.player_token,
            close_code,
        )

        if not self.accepted:
            logger.info(
                "SKIP auto-surrender | WS never accepted | "
                "Game=%s | Player=%s | code=%s",
                self.game_id,
                self.player_token,
                close_code,
            )
            return

        if not self.player_token:
            return

        state = await database_sync_to_async(gss.get_state)(self.game_id)
        if (
            not state
            or state.get("game_status") not in ("LOBBY", "ACTIVE")
            or self.player_token not in state.get("player_assignments", {})
        ):
            return

        await database_sync_to_async(gss.mark_player_away)(
            self.game_id, self.player_token
        )
        await database_sync_to_async(gss.set_surrender_deadline)(
            self.game_id, self.player_token, AUTO_SURRENDER_GRACE_SECONDS
        )

        task_key = f"{self.game_id}:{self.player_token}"
        existing = PENDING_SURRENDER_TASKS.pop(task_key, None)
        if existing:
            existing.cancel()

        task = asyncio.create_task(
            _auto_surrender_task(
                self.game_id, self.player_token, self.channel_layer
            )
        )
        PENDING_SURRENDER_TASKS[task_key] = task
        logger.info(
            "AUTO-SURRENDER SCHEDULED | Game=%s | Player=%s | %ss",
            self.game_id,
            self.player_token,
            AUTO_SURRENDER_GRACE_SECONDS,
        )

    def get_active_player_colors(self, state):
        assignments = state.get("player_assignments", {})
        colors = []
        for color in assignments.values():
            if color not in colors:
                colors.append(color)
        return colors

    def normalize_turn_order(self, state):
        if state.get("game_status") != "ACTIVE":
            return
        active_colors = self.get_active_player_colors(state)
        if not active_colors:
            return
        existing_order = state.get("player_turn_order", [])
        new_order = []
        for color in existing_order:
            if color in active_colors and color not in new_order:
                new_order.append(color)
        for color in active_colors:
            if color not in new_order:
                new_order.append(color)
        state["player_turn_order"] = new_order
        state["turn_index"] = (
            0 if not new_order else state.get("turn_index", 0) % len(new_order)
        )

    def is_current_players_turn(self, state):
        self.normalize_turn_order(state)
        order = state.get("player_turn_order", [])
        if not order:
            return False
        current_color = order[state["turn_index"]]
        assigned_color = state["player_assignments"].get(self.player_token)
        return current_color == assigned_color

    def get_device_for_color(self, state, color):
        for device_token, assigned_color in state[
            "player_assignments"
        ].items():
            if assigned_color == color:
                return device_token
        return None

    def has_player_won(self, state, color):
        player_tokens = [
            token for token in state["tokens"] if token["color"] == color
        ]
        return len(player_tokens) == 4 and all(
            token["position"] == 56 for token in player_tokens
        )

    @database_sync_to_async
    def payout_winner(
        self, game_id, winning_device_token, surrendered_tokens=None
    ):
        return finalize_wager_game(
            game_id=game_id,
            winning_device_token=winning_device_token,
            surrendered_tokens=surrendered_tokens,
        )

    async def handle_game_winner(self, state, winning_color):
        winning_device_token = self.get_device_for_color(state, winning_color)
        if not winning_device_token:
            state["game_status"] = "PAYOUT_ERROR"
            state["status_text"] = (
                "Winner detected, but player identity not found."
            )
            logger.error(
                "PAYOUT ERROR | Game=%s | Color=%s | Device not found",
                self.game_id,
                winning_color,
            )
            await database_sync_to_async(gss.set_state)(self.game_id, state)
            return

        await _ensure_game_room_exists(self.game_id, state)

        try:
            result = await self.payout_winner(
                self.game_id,
                winning_device_token,
                state.get("surrendered_tokens", []),
            )
        except Exception:
            state["game_status"] = "PAYOUT_ERROR"
            state["status_text"] = (
                "Winner detected, but an internal payout error occurred."
            )
            logger.exception(
                "PAYOUT EXCEPTION | Game=%s | Winner=%s",
                self.game_id,
                winning_device_token,
            )
            await database_sync_to_async(gss.set_state)(self.game_id, state)
            return

        if (
            not isinstance(result, dict)
            or result.get("status") != "success"
        ):
            state["game_status"] = "PAYOUT_ERROR"
            state["status_text"] = (
                f"{winning_color} won, but payout failed: "
                f"{result.get('message', 'Unknown') if isinstance(result, dict) else 'Unknown'}"
            )
            logger.error(
                "PAYOUT FAILED | Game=%s | Winner=%s | Reason=%s",
                self.game_id,
                winning_device_token,
                result.get("message", "Unknown") if isinstance(result, dict) else "Unknown",
            )
            await database_sync_to_async(gss.set_state)(self.game_id, state)
            return

        state["winner"] = winning_color
        state["winner_device_token"] = winning_device_token
        state["game_status"] = "COMPLETED"
        state["winner_payout"] = int(result.get("winner_payout", 0))
        state["platform_fee"] = int(result.get("service_fee", 0))
        state["total_pool"] = int(result.get("total_pool", 0))
        state["status_text"] = (
            f"{winning_color} WON! {state['winner_payout']} coins awarded."
        )

        _cancel_turn_timer(self.game_id)
        await database_sync_to_async(gss.set_state)(self.game_id, state)

        logger.info(
            "GAME WON | Game=%s | Winner=%s | Payout=%s",
            self.game_id,
            winning_color,
            state["winner_payout"],
        )

    async def handle_surrender(self, state):
        current_status = state.get("game_status")

        if current_status == "ACTIVE":
            leaver_color, remaining = _remove_player_from_state(
                state, self.player_token
            )
            logger.info(
                "SURRENDER | Game=%s | Leaver=%s | Remaining=%s",
                self.game_id,
                self.player_token,
                len(remaining),
            )

            if len(remaining) == 0:
                await database_sync_to_async(cancel_wager)(self.game_id)
                state["game_status"] = "CANCELLED"
                state["status_text"] = "All players left. Game cancelled."
                await database_sync_to_async(gss.set_state)(self.game_id, state)
                _cancel_turn_timer(self.game_id)
                await self.broadcast_current_state(state=state)
                return

            if len(remaining) == 1:
                winner_token, winner_color = remaining[0]
                state["status_text"] = (
                    f"{leaver_color} surrendered! {winner_color} wins."
                )
                await self.handle_game_winner(state, winner_color)
                await self.broadcast_current_state(state=state)
                return

            state["status_text"] = (
                f"{leaver_color} surrendered. Game continues."
            )
            self.normalize_turn_order(state)
            if not state["player_turn_order"]:
                state["game_status"] = "CANCELLED"
            await self.broadcast_current_state(
                state=state, force_timer_reset=True
            )
            return

        if current_status == "LOBBY":
            await database_sync_to_async(cancel_wager)(self.game_id)
            state["game_status"] = "CANCELLED"
            state["status_text"] = "Match cancelled. Coins refunded."
            logger.info(
                "LOBBY CANCELLED + REFUND | Game=%s | Player=%s",
                self.game_id,
                self.player_token,
            )
            await database_sync_to_async(gss.set_state)(self.game_id, state)
            _cancel_turn_timer(self.game_id)
            await self.broadcast_current_state(state=state)
            return

        await self.broadcast_current_state(state=state)

    async def handle_skip_turn(self, state):
        if state.get("game_status") != "ACTIVE":
            return

        def _skip(st):
            if st.get("game_status") != "ACTIVE":
                return None
            order = st.get("player_turn_order", [])
            if not order:
                return None
            current_color = order[st.get("turn_index", 0)]
            assigned = st.get("player_assignments", {}).get(self.player_token)
            if assigned != current_color:
                return None
            st["has_rolled"] = False
            st["turn_index"] = (st["turn_index"] + 1) % len(order)
            next_color = order[st["turn_index"]]
            st["turn_deadline"] = time.time() + TURN_TIMEOUT_SECONDS
            st["status_text"] = (
                f"⏰ {current_color} timed out! {next_color}'s Turn"
            )
            return (current_color, next_color)

        try:
            result = await database_sync_to_async(gss.mutate_game)(
                self.game_id, _skip
            )
        except gss.LockTimeout:
            logger.warning(
                "SKIP TURN lock timeout | Game=%s", self.game_id
            )
            return

        if result is None:
            fresh_state = await database_sync_to_async(gss.get_state)(
                self.game_id
            )
            if fresh_state:
                await self.broadcast_current_state(state=fresh_state)
            return

        current_color, next_color = result
        logger.info(
            "SKIP TURN | Game=%s | From=%s | To=%s",
            self.game_id,
            current_color,
            next_color,
        )

        fresh_state = await database_sync_to_async(gss.get_state)(
            self.game_id
        )
        if fresh_state:
            await self.broadcast_current_state(
                state=fresh_state, force_timer_reset=True
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        action = data.get("action")

        # ✅ F3 — Chat message (works during LOBBY + ACTIVE)
        if action == "chat_message":
            text = str(data.get("text", "")).strip()
            if not text or len(text) > 100:
                return

            state = await database_sync_to_async(gss.get_state)(self.game_id)
            if not state:
                return

            names = state.get("player_names", {})
            sender_name = names.get(self.player_token, "Player")
            sender_color = state.get("player_assignments", {}).get(self.player_token)

            message = {
                "sender": self.player_token or "",
                "sender_name": sender_name,
                "sender_color": sender_color or "",
                "text": text,
                "ts": time.time(),
            }

            def _add_chat(st):
                msgs = st.setdefault("chat_messages", [])
                msgs.append(message)
                if len(msgs) > 20:
                    del msgs[: len(msgs) - 20]
                return True

            try:
                await database_sync_to_async(gss.mutate_game)(self.game_id, _add_chat)
            except gss.LockTimeout:
                logger.warning("CHAT lock timeout | Game=%s", self.game_id)
                return

            logger.info(
                "CHAT | Game=%s | From=%s | %s",
                self.game_id, sender_name, text[:40],
            )

            await self.channel_layer.group_send(
                self.room_group_name,
                {"type": "chat_notification", "message": message},
            )
            return

        # ✅ F2 — Rematch notification
        if action == "rematch_request":
            state = await database_sync_to_async(gss.get_state)(self.game_id)
            from_name = "Player"
            if state:
                names = state.get("player_names", {})
                from_name = names.get(self.player_token, "Player")

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "rematch_notification",
                    "from_player": self.player_token or "",
                    "from_name": from_name,
                },
            )
            logger.info(
                "REMATCH REQUEST | Game=%s | From=%s | Name=%s",
                self.game_id, self.player_token, from_name,
            )
            return

        # ✅ NEW: Voice Call Invite
        if action == "voice_call_invite":
            state = await database_sync_to_async(gss.get_state)(self.game_id)
            from_name = "Player"
            if state:
                names = state.get("player_names", {})
                from_name = names.get(self.player_token, "Player")

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "voice_invite_notification",
                    "from_player": self.player_token or "",
                    "from_name": from_name,
                },
            )
            logger.info(
                "VOICE INVITE | Game=%s | From=%s | Name=%s",
                self.game_id, self.player_token, from_name,
            )
            return

        state = await database_sync_to_async(gss.get_state)(self.game_id)
        if not state:
            return

        try:
            if action == "surrender":
                await self.handle_surrender(state)
                return

            if state.get("game_status") in ("COMPLETED", "PAYOUT_ERROR"):
                await self.broadcast_current_state(state=state)
                return

            if action == "roll_dice":
                if not self.is_current_players_turn(state):
                    logger.warning(
                        "REJECTED ROLL | Game=%s | Player=%s",
                        self.game_id,
                        self.player_token,
                    )
                    return
                await self.handle_dice_roll(state)
                await self.broadcast_current_state(state=state)

            elif action == "move_token":
                if not self.is_current_players_turn(state):
                    logger.warning(
                        "REJECTED MOVE | Game=%s | Player=%s",
                        self.game_id,
                        self.player_token,
                    )
                    return
                granted_bonus = await self.handle_token_movement(
                    state, data.get("token_id"), data.get("color")
                )
                await self.broadcast_current_state(
                    state=state,
                    force_timer_reset=bool(granted_bonus),
                )

            elif action == "skip_turn":
                await self.handle_skip_turn(state)
                return

            else:
                await self.broadcast_current_state(state=state)

        except gss.LockTimeout:
            logger.warning(
                "LOCK TIMEOUT | Game=%s | Player=%s",
                self.game_id,
                self.player_token,
            )

    async def handle_dice_roll(self, state):
        self.normalize_turn_order(state)
        if state["has_rolled"]:
            return

        roll = random.randint(1, 6)
        state["current_dice_value"] = roll
        state["has_rolled"] = True

        current_player = state["player_turn_order"][state["turn_index"]]
        player_tokens = [
            token
            for token in state["tokens"]
            if token["color"] == current_player
        ]

        valid_moves = 0
        for token in player_tokens:
            if token["position"] == -1 and roll == 6:
                valid_moves += 1
            elif 0 <= token["position"] <= 55 and (
                token["position"] + roll <= 56
            ):
                valid_moves += 1

        if valid_moves == 0:
            state["has_rolled"] = False
            state["turn_index"] = (
                state["turn_index"] + 1
            ) % len(state["player_turn_order"])
            next_player = state["player_turn_order"][state["turn_index"]]
            state["turn_deadline"] = time.time() + TURN_TIMEOUT_SECONDS
            state["status_text"] = (
                f"{current_player} rolled {roll} (No Moves)! "
                f"Pass to {next_player}."
            )
        else:
            state["status_text"] = (
                f"{current_player} rolled {roll}! Select your token."
            )
        return False

    async def handle_token_movement(self, state, token_id, color):
        if not state["has_rolled"]:
            return False

        self.normalize_turn_order(state)
        current_player = state["player_turn_order"][state["turn_index"]]
        if color != current_player:
            state["status_text"] = (
                f"It is not {color}'s turn! "
                f"It is {current_player}'s turn."
            )
            return False

        token = next(
            (
                t
                for t in state["tokens"]
                if t["id"] == token_id and t["color"] == color
            ),
            None,
        )
        if not token:
            return False

        roll = state["current_dice_value"]
        move_executed = False
        grant_bonus_roll = (roll == 6)

        if token["position"] == -1 and roll == 6:
            token["position"] = 0
            move_executed = True
            state["status_text"] = (
                f"{color} moved a token out of the base!"
            )
        elif 0 <= token["position"] <= 55:
            target_destination = token["position"] + roll
            if target_destination <= 56:
                token["position"] = target_destination
                move_executed = True
                state["status_text"] = (
                    f"{color} moved a token forward by {roll}."
                )

                target_global_cell = get_global_cell_index(
                    color, target_destination
                )
                if (
                    target_global_cell is not None
                    and target_global_cell not in SAFE_GLOBAL_CELLS
                ):
                    for enemy_token in state["tokens"]:
                        if (
                            enemy_token["color"] != color
                            and enemy_token["position"] >= 0
                        ):
                            enemy_global_cell = get_global_cell_index(
                                enemy_token["color"],
                                enemy_token["position"],
                            )
                            if enemy_global_cell == target_global_cell:
                                enemy_token["position"] = -1
                                grant_bonus_roll = True
                                state["status_text"] = (
                                    f"{color} kicked out "
                                    f"{enemy_token['color']}! "
                                    f"Bonus roll granted."
                                )

        if not move_executed:
            state["status_text"] = (
                f"Invalid move for that token! "
                f"{color}, select a valid token."
            )
            return False

        state["has_rolled"] = False

        if self.has_player_won(state, color):
            state["winner"] = color
            state["game_status"] = "WON"
            state["status_text"] = (
                f"{color} WON THE GAME! Processing payout..."
            )
            await self.handle_game_winner(state, color)
            return False

        if token["position"] == 56:
            grant_bonus_roll = True
            state["status_text"] = (
                f"{color} reached the goal! Bonus roll granted."
            )

        if not grant_bonus_roll:
            self.normalize_turn_order(state)
            state["turn_index"] = (
                state["turn_index"] + 1
            ) % len(state["player_turn_order"])
            next_player = state["player_turn_order"][state["turn_index"]]
            state["turn_deadline"] = time.time() + TURN_TIMEOUT_SECONDS
            state["status_text"] = (
                f"{next_player}'s Turn! Tap the dice to roll."
            )
        else:
            state["turn_deadline"] = time.time() + TURN_TIMEOUT_SECONDS
            state["status_text"] = (
                f"{color}'s Bonus Roll! Tap the dice."
            )

        return grant_bonus_roll

    async def broadcast_current_state(
        self, state=None, force_timer_reset=False
    ):
        if state is None:
            state = await database_sync_to_async(gss.get_state)(
                self.game_id
            )
        if not state:
            return

        self.normalize_turn_order(state)

        if state.get("game_status") == "ACTIVE":
            now = time.time()
            current_deadline = float(state.get("turn_deadline", 0) or 0)
            if force_timer_reset or current_deadline <= 0:
                state["turn_deadline"] = now + TURN_TIMEOUT_SECONDS

        await database_sync_to_async(gss.set_state)(self.game_id, state)

        if state.get("game_status") == "ACTIVE":
            _ensure_turn_loop(self.game_id, self.channel_layer)

        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "send_state_payload", "payload": state},
        )

    async def send_state_payload(self, event):
        await self.send(
            text_data=json.dumps(
                {"status": "success", "game_state": event["payload"]}
            )
        )

    async def rematch_notification(self, event):
        """✅ F2 — Broadcast rematch request."""
        await self.send(
            text_data=json.dumps({
                "type": "rematch_request",
                "from_player": event["from_player"],
                "from_name": event["from_name"],
            })
        )

    async def chat_notification(self, event):
        """✅ F3 — Broadcast chat message."""
        await self.send(
            text_data=json.dumps({
                "type": "chat_message",
                "message": event["message"],
            })
        )

    # ✅ NEW: Voice Invite Notification
    async def voice_invite_notification(self, event):
        await self.send(
            text_data=json.dumps({
                "type": "voice_call_invite",
                "from_player": event["from_player"],
                "from_name": event["from_name"],
            })
        )