# myapp/management/commands/ludo_sweeper.py

import logging
import time
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from myapp.models import GameRoom, UserProfileBalance
from myapp.services import game_state_store as gss
from myapp.services.wager_service import finalize_wager_game, cancel_wager

logger = logging.getLogger("myapp.sweeper")

TURN_TIMEOUT_SECONDS = 25                # ✅ P2-1
SURRENDER_GRACE_SECONDS = 60             # ✅ P2-1
PRIVATE_LOBBY_IDLE_SECONDS = 15 * 60
ORPHAN_ACTIVE_GRACE_SECONDS = 60
CONSUMER_HEARTBEAT_TTL = 30


class Command(BaseCommand):
    help = "Sweep stale turn timers, surrenders, and private rooms."

    def handle(self, *args, **opts):
        try:
            self._sweep_turn_timeouts()
            self._sweep_surrenders()
            self._sweep_orphan_active_games()
            self._sweep_stale_lobbies()
        except Exception:
            logger.exception("Sweeper iteration failed")


    def _sweep_turn_timeouts(self):

        for game_id, state in gss.iter_all_states():

            if state.get("game_status") != "ACTIVE":
                continue

            expected = state.get("turn_index", 0)

            if gss.get_turn_deadline(game_id) is not None:
                continue

            # ✅ P1-8: skip if consumer heartbeat is alive
            try:
                r = gss._get_redis()
                if r.get(f"ludo:consumer_hb:{game_id}") is not None:
                    continue
            except Exception:
                pass

            try:
                with gss.game_lock(game_id, wait_timeout=2):

                    state = gss.get_state(game_id)

                    if (
                        not state
                        or state.get("game_status") != "ACTIVE"
                        or state.get("turn_index") != expected
                    ):
                        continue

                    order = state.get("player_turn_order", [])
                    if not order:
                        continue

                    state["has_rolled"] = False
                    state["turn_index"] = (state["turn_index"] + 1) % len(order)
                    next_color = order[state["turn_index"]]
                    state["status_text"] = f"⏰ Time out! {next_color}'s Turn"

                    gss.set_state(game_id, state)
                    logger.info("TURN TIMEOUT | Game=%s | Next=%s", game_id, next_color)

                    self._broadcast(game_id, state)
                    gss.set_turn_deadline(
                        game_id, state["turn_index"], TURN_TIMEOUT_SECONDS,
                    )

            except gss.LockTimeout:
                continue
            except Exception:
                logger.exception("Turn sweep failed for %s", game_id)


    def _sweep_surrenders(self):
        for game_id, player_token in list(gss.iter_expired_surrenders()):
            try:
                with gss.game_lock(game_id, wait_timeout=2):
                    state = gss.get_state(game_id)
                    if (
                        not state
                        or state.get("game_status") not in ("LOBBY", "ACTIVE")
                        or player_token not in state.get("player_assignments", {})
                    ):
                        continue

                    logger.info(
                        "AUTO-SURRENDER | Game=%s | Player=%s",
                        game_id, player_token,
                    )

                    from myapp.consumers import _remove_player_from_state

                    leaver_color, remaining = _remove_player_from_state(
                        state, player_token,
                    )

                    if state["game_status"] == "LOBBY":
                        cancel_wager(game_id)
                        state["game_status"] = "CANCELLED"
                        state["status_text"] = "Player abandoned room. Game cancelled."
                        gss.set_state(game_id, state)
                        self._broadcast(game_id, state)
                        gss.clear_turn_deadline(game_id)
                        continue

                    if not remaining:
                        cancel_wager(game_id)
                        state["game_status"] = "CANCELLED"
                        state["status_text"] = "All players left. Cancelled."

                    elif len(remaining) == 1:
                        winner_token, winner_color = remaining[0]
                        result = finalize_wager_game(
                            game_id=game_id,
                            winning_device_token=winner_token,
                            surrendered_tokens=state.get("surrendered_tokens", []),
                        )
                        if result.get("status") == "success":
                            state["game_status"] = "COMPLETED"
                            state["winner"] = winner_color
                            state["winner_device_token"] = winner_token
                            state["winner_payout"] = int(result.get("winner_payout", 0))
                            state["status_text"] = (
                                f"{winner_color} WON! {state['winner_payout']} coins."
                            )
                        else:
                            state["game_status"] = "PAYOUT_ERROR"
                            state["status_text"] = (
                                f"Payout failed: {result.get('message', '?')}"
                            )
                        gss.clear_turn_deadline(game_id)

                    else:
                        state["status_text"] = (
                            f"{leaver_color} disconnected. Game continues."
                        )

                    gss.set_state(game_id, state)
                    self._broadcast(game_id, state)

            except gss.LockTimeout:
                continue
            except Exception:
                logger.exception("Surrender sweep failed for %s", game_id)


    # ==========================================================
    # ✅ P1-8 FIX: Orphan cleanup now checks consumer heartbeat
    #
    # Game is orphan if:
    #   - status = ACTIVE
    #   - ALL players marked away (no live WS)
    #   - No surrender deadline pending
    #   - ✅ No consumer heartbeat (loop dead)
    # ==========================================================

    def _sweep_orphan_active_games(self):
        r = gss._get_redis()

        for game_id, state in list(gss.iter_all_states()):

            if state.get("game_status") != "ACTIVE":
                continue

            assignments = state.get("player_assignments", {})

            if not assignments:
                logger.warning("ORPHAN ACTIVE GAME (no players) | Game=%s", game_id)
                self._cancel_orphan(game_id, "No players assigned")
                continue

            # ✅ P1-8: if consumer heartbeat alive, game is being managed
            try:
                hb = r.get(f"ludo:consumer_hb:{game_id}")
                if hb is not None:
                    continue    # turn loop is alive
            except Exception:
                pass

            any_connected = False
            any_pending_surrender = False

            for token in assignments.keys():
                away_key = f"ludo:away:{game_id}:{token}"
                surrender_key = f"ludo:surrender_deadline:{game_id}:{token}"

                if r.get(away_key) is None:
                    any_connected = True
                    break
                if r.get(surrender_key) is not None:
                    any_pending_surrender = True

            if any_connected or any_pending_surrender:
                continue

            logger.warning(
                "ORPHAN ACTIVE GAME DETECTED | Game=%s "
                "| All players away, no surrender pending, no heartbeat",
                game_id,
            )

            self._cancel_orphan(
                game_id, "All players disconnected (orphan cleanup)",
            )


    def _cancel_orphan(self, game_id, reason):
        try:
            with gss.game_lock(game_id, wait_timeout=2):
                state = gss.get_state(game_id)
                if not state or state.get("game_status") != "ACTIVE":
                    return

                assignments = state.get("player_assignments", {})
                if assignments:
                    r = gss._get_redis()
                    # ✅ P1-8: double-check heartbeat inside lock
                    if r.get(f"ludo:consumer_hb:{game_id}") is not None:
                        return
                    still_connected = False
                    for token in assignments.keys():
                        if r.get(f"ludo:away:{game_id}:{token}") is None:
                            still_connected = True
                            break
                    if still_connected:
                        return

                logger.info("ORPHAN CLEANUP | Game=%s | Reason=%s", game_id, reason)

                cancel_wager(game_id)

                state["game_status"] = "CANCELLED"
                state["status_text"] = reason
                gss.set_state(game_id, state)
                self._broadcast(game_id, state)
                gss.clear_turn_deadline(game_id)

                r = gss._get_redis()
                for token in assignments.keys():
                    r.delete(f"ludo:away:{game_id}:{token}")
                    r.delete(f"ludo:surrender_deadline:{game_id}:{token}")
                r.delete(f"ludo:consumer_hb:{game_id}")

        except gss.LockTimeout:
            logger.warning("ORPHAN CLEANUP lock timeout | Game=%s", game_id)
        except Exception:
            logger.exception("Orphan cleanup failed for %s", game_id)


    def _sweep_stale_lobbies(self):
        cutoff = timezone.now() - timedelta(seconds=PRIVATE_LOBBY_IDLE_SECONDS)
        stale = GameRoom.objects.filter(
            is_private=True,
            game_status="LOBBY",
            updated_at__lt=cutoff,
        )
        for game in stale:
            try:
                with transaction.atomic():
                    game = (
                        GameRoom.objects.select_for_update()
                        .filter(id=game.id, game_status="LOBBY")
                        .first()
                    )
                    if not game:
                        continue
                    logger.info("STALE PRIVATE LOBBY | Game=%s", game.game_id)
                    cancel_wager(game.game_id)
                    gss.delete_state(game.game_id)
            except Exception:
                logger.exception("Stale lobby cleanup failed for %s", game.game_id)


    @staticmethod
    def _broadcast(game_id, state):
        layer = get_channel_layer()
        if not layer:
            return
        try:
            async_to_sync(layer.group_send)(
                f"ludo_match_{game_id}",
                {"type": "send_state_payload", "payload": state},
            )
        except Exception:
            logger.exception("Broadcast failed for %s", game_id)