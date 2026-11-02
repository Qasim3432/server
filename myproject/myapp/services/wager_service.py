# myapp/services/wager_service.py

import logging
import time

from django.db import transaction, OperationalError
from ..models import (
    GameRoom, GameHistory, UserProfileBalance, 
    SystemTransactionLog, ReferralSystem, 
    SystemConfiguration, WithdrawalRequest,
)
from ..currency_utils import format_dollar

logger = logging.getLogger("myapp.services.wager_service")


# ==========================================================
# RETRY HELPER — database is locked
#
# SQLite serializes writers. When two players join
# simultaneously, one gets "database is locked".
# Retry with exponential backoff.
# ==========================================================

DB_LOCK_MAX_RETRIES = 5
DB_LOCK_BASE_DELAY = 0.15


def _is_db_lock_error(exc):
    return "database is locked" in str(exc).lower()


def _retry_on_db_lock(fn, *args, **kwargs):
    last_error = None
    for attempt in range(DB_LOCK_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except OperationalError as exc:
            if not _is_db_lock_error(exc):
                raise
            last_error = exc
            delay = DB_LOCK_BASE_DELAY * (attempt + 1)
            logger.warning(
                "DB LOCK retry %s/%s | %s | waiting %.2fs",
                attempt + 1,
                DB_LOCK_MAX_RETRIES,
                fn.__name__,
                delay,
            )
            time.sleep(delay)
    logger.error(
        "DB LOCK max retries exhausted | %s", fn.__name__,
    )
    raise last_error


# ==========================================================
# HELPERS — STALE GAME CLEANUP
# ==========================================================

def _release_locked_for_game(game):

    for player in game.players.select_for_update().all():

        release_amount = min(player.locked_coins, game.bet_amount)

        if release_amount <= 0:
            continue

        player.locked_coins -= release_amount
        player.coins += release_amount
        player.save(update_fields=["coins", "locked_coins"])

        SystemTransactionLog.objects.create(
            user_profile=player,
            amount=release_amount,
            log_type="WAGER_REFUND",
            reference_id=f"AUTO_CANCEL_{game.game_id}",
        )

    game.game_status = "CANCELLED"
    game.total_pool_escrow = 0
    game.save(update_fields=["game_status", "total_pool_escrow"])

    try:
        from . import game_state_store as gss
        gss.delete_state(str(game.game_id))
    except Exception:
        pass


def _cancel_prior_active_games(device_token, exclude_game_id=None):

    id_queryset = GameRoom.objects.filter(
        players__device_token=device_token,
        game_status="ACTIVE",
    ).distinct()

    if exclude_game_id:
        id_queryset = id_queryset.exclude(game_id=exclude_game_id)

    game_ids = list(id_queryset.values_list("id", flat=True))

    if not game_ids:
        return 0

    prior_games = list(
        GameRoom.objects.select_for_update().filter(id__in=game_ids)
    )

    for prior in prior_games:
        _release_locked_for_game(prior)

    return len(prior_games)


def _determine_max_players(game_id, existing_game=None):
    try:
        from . import game_state_store as gss
        state = gss.get_state(str(game_id))
        if state:
            return 2 if state.get("is_two_player_mode", True) else 4
    except Exception:
        pass
    if existing_game is not None:
        return existing_game.max_players
    return 2


def _record_game_history(
    game,
    participants,
    winning_device_token,
    cancelled=False,
    surrendered_tokens=None,
):

    surrendered_tokens = set(surrendered_tokens or [])

    player_count = len(participants)
    game_mode = "4P" if player_count >= 3 else "2P"
    opponent_count = max(1, player_count - 1)

    for player in participants:

        if cancelled:
            result = "CANCELLED"
            coins_change = 0

        elif player.device_token in surrendered_tokens:
            result = "SURRENDERED"
            coins_change = -game.bet_amount

        elif player.device_token == winning_device_token:
            result = "WON"
            coins_change = int(game.winner_payout or 0) - game.bet_amount

        else:
            result = "LOST"
            coins_change = -game.bet_amount

        GameHistory.objects.create(
            user_profile=player,
            game_id=str(game.game_id),
            bet_amount=game.bet_amount,
            result=result,
            coins_change=coins_change,
            game_mode=game_mode,
            opponent_count=opponent_count,
        )


# ==========================================================
# WAGER JOIN SERVICE
#
# ✅ Wrapped in _retry_on_db_lock → handles SQLite locks
# ==========================================================

def _join_wager_impl(device_token, game_id, bet_amount):

    with transaction.atomic():

        profile = (
            UserProfileBalance.objects
            .select_for_update()
            .filter(device_token=device_token)
            .first()
        )

        if not profile:
            return {
                "status": "error",
                "message": "User wallet profile not found.",
            }

        try:
            bet_amount = int(bet_amount)
        except (TypeError, ValueError):
            return {"status": "error", "message": "Invalid bet amount."}

        if bet_amount <= 0:
            return {
                "status": "error",
                "message": "Bet amount must be greater than zero.",
            }

        if not game_id:
            return {"status": "error", "message": "Game ID is required."}

        _cancel_prior_active_games(
            device_token=device_token,
            exclude_game_id=game_id,
        )

        profile.refresh_from_db()

        if profile.coins < bet_amount:
            return {
                "status": "error",
                "message": (
                    f"Insufficient funds. "
                    f"Required: {format_dollar(bet_amount)}, "
                    f"Available: {format_dollar(profile.coins)}."
                ),
            }

        max_players = _determine_max_players(game_id=game_id)

        game, created = (
            GameRoom.objects
            .select_for_update()
            .get_or_create(
                game_id=game_id,
                defaults={
                    "bet_amount": bet_amount,
                    "game_status": "LOBBY",
                    "total_pool_escrow": 0,
                    "max_players": max_players,
                },
            )
        )

        if not created:
            state_max = _determine_max_players(
                game_id=game_id,
                existing_game=game,
            )
            if state_max != game.max_players:
                game.max_players = state_max
                game.save(update_fields=["max_players"])

        if game.game_status != "LOBBY":
            return {
                "status": "error",
                "message": "This game is no longer accepting players.",
            }

        if game.bet_amount != bet_amount:
            return {
                "status": "error",
                "message": (
                    f"Incorrect bet amount. "
                    f"This room requires {format_dollar(game.bet_amount)}."
                ),
            }

        existing_player = game.players.filter(
            device_token=device_token
        ).first()

        if existing_player:

            if game.game_status == "LOBBY":

                release_amount = min(
                    existing_player.locked_coins,
                    game.bet_amount,
                )

                if release_amount > 0:
                    existing_player.locked_coins -= release_amount
                    existing_player.coins += release_amount
                    existing_player.save(
                        update_fields=["coins", "locked_coins"]
                    )
                    SystemTransactionLog.objects.create(
                        user_profile=existing_player,
                        amount=release_amount,
                        log_type="WAGER_REFUND",
                        reference_id=f"REJOIN_{game_id}",
                    )

                game.players.remove(existing_player)
                game.total_pool_escrow = max(
                    0, game.total_pool_escrow - release_amount
                )
                profile.refresh_from_db()

            else:
                return {
                    "status": "error",
                    "message": "Player has already joined this game.",
                }

        if game.players.count() >= game.max_players:
            return {
                "status": "error",
                "message": "This game already has enough players.",
            }

        profile.coins -= bet_amount
        profile.locked_coins += bet_amount
        profile.save(update_fields=["coins", "locked_coins"])

        SystemTransactionLog.objects.create(
            user_profile=profile,
            amount=-bet_amount,
            log_type="WAGER_ESCROW",
            reference_id=str(game_id),
        )

        game.players.add(profile)
        game.total_pool_escrow += bet_amount

        if game.players.count() >= game.max_players:

            game.game_status = "ACTIVE"

            config = SystemConfiguration.get_solo()

            game.service_fee_cut = int(
                (game.total_pool_escrow * config.platform_tax_percentage) / 100
            )
            game.winner_payout = (
                game.total_pool_escrow - game.service_fee_cut
            )

        game.save()

        return {
            "status": "success",
            "message": "Entry fee locked successfully.",
            "game_id": str(game.game_id),
            "game_status": game.game_status,
            "coins": profile.coins,
            "locked_coins": profile.locked_coins,
            "bet_amount": game.bet_amount,
            "total_pool_escrow": game.total_pool_escrow,
            "service_fee_cut": int(game.service_fee_cut or 0),
            "winner_payout": int(game.winner_payout or 0),
            "max_players": game.max_players,
        }


def join_wager(device_token, game_id, bet_amount):

    return _retry_on_db_lock(
        _join_wager_impl,
        device_token,
        game_id,
        bet_amount,
    )


# ==========================================================
# FINALIZE
# ==========================================================

def _finalize_impl(game_id, winning_device_token, surrendered_tokens=None):

    with transaction.atomic():

        game = (
            GameRoom.objects
            .select_for_update()
            .filter(game_id=game_id)
            .first()
        )

        if not game:
            return {"status": "error", "message": "Game room not found."}

        if game.game_status != "ACTIVE":
            return {
                "status": "error",
                "message": f"Game status is {game.game_status}",
            }

        if not winning_device_token:
            return {
                "status": "error",
                "message": "Winning device token is required.",
            }

        winner = (
            game.players
            .select_for_update()
            .filter(device_token=winning_device_token)
            .first()
        )

        if not winner:
            return {
                "status": "error",
                "message": "Winning player is not a participant.",
            }

        winner_payout = int(game.winner_payout or 0)
        service_fee = int(game.service_fee_cut or 0)
        total_pool = int(game.total_pool_escrow or 0)

        if winner_payout + service_fee != total_pool:
            return {
                "status": "error",
                "message": "Payout calculation mismatch.",
            }

        participants = list(game.players.select_for_update().all())

        if not participants:
            return {
                "status": "error",
                "message": "Game has no participants.",
            }

        for player in participants:
            if player.locked_coins < game.bet_amount:
                return {
                    "status": "error",
                    "message": (
                        f"Invalid locked balance for {player.device_token}."
                    ),
                }

        game.game_status = "COMPLETED"
        game.save(update_fields=["game_status"])

        for player in participants:
            player.locked_coins -= game.bet_amount
            if player.device_token == winning_device_token:
                player.coins += winner_payout
            player.save(update_fields=["coins", "locked_coins"])

        SystemTransactionLog.objects.create(
            user_profile=winner,
            amount=winner_payout,
            log_type="WAGER_PAYOUT",
            reference_id=str(game.game_id),
        )

        admin_profile, _ = (
            UserProfileBalance.objects
            .select_for_update()
            .get_or_create(device_token="SYSTEM_PLATFORM_ADMIN_LEDGER")
        )
        admin_profile.coins += service_fee
        admin_profile.save(update_fields=["coins"])

        _record_game_history(
            game=game,
            participants=participants,
            winning_device_token=winning_device_token,
            cancelled=False,
            surrendered_tokens=surrendered_tokens,
        )

        return {
            "status": "success",
            "message": "Payout completed.",
            "game_id": str(game.game_id),
            "winner": winning_device_token,
            "winner_payout": winner_payout,
            "service_fee": service_fee,
            "total_pool": total_pool,
        }


def finalize_wager_game(game_id, winning_device_token, surrendered_tokens=None):

    return _retry_on_db_lock(
        _finalize_impl,
        game_id,
        winning_device_token,
        surrendered_tokens,
    )


def finalize_wager(game_id, winning_device_token, surrendered_tokens=None):
    return finalize_wager_game(
        game_id=game_id,
        winning_device_token=winning_device_token,
        surrendered_tokens=surrendered_tokens,
    )


# ==========================================================
# CANCEL
# ==========================================================

def _cancel_impl(game_id):

    with transaction.atomic():

        game = (
            GameRoom.objects
            .select_for_update()
            .filter(game_id=game_id)
            .first()
        )

        if not game:
            return {"status": "error", "message": "Game room not found."}

        if game.game_status in ("COMPLETED", "CANCELLED"):
            return {
                "status": "error",
                "message": f"Game already processed: {game.game_status}",
            }

        participants = list(game.players.select_for_update().all())

        for player in participants:
            if player.locked_coins < game.bet_amount:
                return {
                    "status": "error",
                    "message": (
                        f"Invalid locked balance for {player.device_token}."
                    ),
                }

        for player in participants:
            player.locked_coins -= game.bet_amount
            player.coins += game.bet_amount
            player.save(update_fields=["coins", "locked_coins"])

            SystemTransactionLog.objects.create(
                user_profile=player,
                amount=game.bet_amount,
                log_type="WAGER_REFUND",
                reference_id=f"CANCEL_{game.game_id}",
            )

        if participants:
            _record_game_history(
                game=game,
                participants=participants,
                winning_device_token=None,
                cancelled=True,
            )

        game.game_status = "CANCELLED"
        game.total_pool_escrow = 0
        game.save(update_fields=["game_status", "total_pool_escrow"])

        return {
            "status": "success",
            "message": "Wager cancelled and balances restored.",
            "game_id": str(game.game_id),
            "players_refunded": len(participants),
        }


def cancel_wager(game_id):
    return _retry_on_db_lock(_cancel_impl, game_id)


# ==========================================================
# WITHDRAWAL APPROVAL
# ==========================================================

def process_withdrawal_approval(withdrawal_id):

    with transaction.atomic():

        withdrawal = (
            WithdrawalRequest.objects
            .select_for_update()
            .filter(id=withdrawal_id, status="PENDING")
            .first()
        )

        if not withdrawal:
            return {
                "status": "error",
                "message": "Pending withdrawal not found.",
            }

        profile = None
        if withdrawal.user_profile_id:
            profile = (
                UserProfileBalance.objects
                .select_for_update()
                .filter(id=withdrawal.user_profile_id)
                .first()
            )
        if not profile:
            profile = (
                UserProfileBalance.objects
                .select_for_update()
                .filter(device_token=withdrawal.device_token)
                .first()
            )
        if not profile:
            return {
                "status": "error",
                "message": "User wallet profile not found.",
            }

        withdrawal.status = "APPROVED"
        withdrawal.save(update_fields=["status"])

        logger.info(
            "WITHDRAWAL APPROVED | device=%s | amount_cents=%s | local=%s %s",
            withdrawal.device_token,
            withdrawal.amount,
            withdrawal.local_amount,
            withdrawal.currency,
        )

        commission = 0

        try:
            config = SystemConfiguration.get_solo()

            referral_mapping = (
                ReferralSystem.objects
                .select_related("referrer")
                .select_for_update()
                .get(referred_user=profile)
            )

            referrer = (
                UserProfileBalance.objects
                .select_for_update()
                .get(id=referral_mapping.referrer.id)
            )

            commission = int(
                (
                    withdrawal.amount
                    * config.withdrawal_commission_percentage
                ) / 100
            )

            if commission > 0:
                referrer.coins += commission
                referrer.save(update_fields=["coins"])

                referral_mapping.total_commission_earned += commission
                referral_mapping.save(
                    update_fields=["total_commission_earned"]
                )

                SystemTransactionLog.objects.create(
                    user_profile=referrer,
                    amount=commission,
                    log_type="REFERRAL_COMMISSION",
                    reference_id=f"WD_REF_{withdrawal.id}",
                )

        except ReferralSystem.DoesNotExist:
            pass

        return {
            "status": "success",
            "message": f"Withdrawal approved ({format_dollar(withdrawal.amount)} → {withdrawal.local_amount} {withdrawal.currency}).",
            "withdrawal_id": withdrawal.id,
            "device_token": withdrawal.device_token,
            "amount": withdrawal.amount,
            "amount_display": format_dollar(withdrawal.amount),
            "local_amount": withdrawal.local_amount,
            "currency": withdrawal.currency,
            "commission": commission,
            "remaining_balance": profile.coins,
        }