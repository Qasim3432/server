# myapp/services/wager_service.py

from django.db import transaction

from ..models import (
    GameRoom,
    UserProfileBalance,
    SystemTransactionLog,
    ReferralSystem,
    SystemConfiguration,
    WithdrawalRequest,
)


# ==========================================================
# WAGER JOIN SERVICE
# ==========================================================

def join_wager(device_token, game_id, bet_amount):
    """
    Adds a player to a wager room.

    Handles:
        - User balance verification
        - Game room creation
        - Duplicate player prevention
        - Wager deduction
        - locked_coins update
        - Escrow ledger entry
        - Room activation when 2 players join
        - Dynamic platform fee calculation
        - Dynamic winner payout calculation
    """

    with transaction.atomic():

        # --------------------------------------------------
        # Validate player
        # --------------------------------------------------

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

        # --------------------------------------------------
        # Validate wager amount
        # --------------------------------------------------

        try:
            bet_amount = int(bet_amount)
        except (TypeError, ValueError):
            return {
                "status": "error",
                "message": "Invalid bet amount.",
            }

        if bet_amount <= 0:
            return {
                "status": "error",
                "message": "Bet amount must be greater than zero.",
            }

        if not game_id:
            return {
                "status": "error",
                "message": "Game ID is required.",
            }

        # --------------------------------------------------
        # Check available balance
        # --------------------------------------------------

        if profile.coins < bet_amount:
            return {
                "status": "error",
                "message": (
                    f"Insufficient funds. "
                    f"Required: {bet_amount}, "
                    f"Available: {profile.coins}"
                ),
            }

        # --------------------------------------------------
        # Get or create game room
        # --------------------------------------------------

        game, created = (
            GameRoom.objects
            .select_for_update()
            .get_or_create(
                game_id=game_id,
                defaults={
                    "bet_amount": bet_amount,
                    "game_status": "LOBBY",
                    "total_pool_escrow": 0,
                },
            )
        )

        # --------------------------------------------------
        # Game must be in lobby
        # --------------------------------------------------

        if game.game_status != "LOBBY":
            return {
                "status": "error",
                "message": (
                    "This game is no longer accepting players."
                ),
            }

        # --------------------------------------------------
        # Existing room bet must match
        # --------------------------------------------------

        if game.bet_amount != bet_amount:
            return {
                "status": "error",
                "message": (
                    f"Incorrect bet amount. "
                    f"This room requires {game.bet_amount} coins."
                ),
            }

        # --------------------------------------------------
        # Prevent duplicate player
        # --------------------------------------------------

        if game.players.filter(
            device_token=device_token
        ).exists():

            return {
                "status": "error",
                "message": (
                    "Player has already joined this game."
                ),
            }

        # --------------------------------------------------
        # Maximum 2 players
        # --------------------------------------------------

        if game.players.count() >= 2:
            return {
                "status": "error",
                "message": (
                    "This game already has enough players."
                ),
            }

        # --------------------------------------------------
        # Deduct wager from available balance
        # --------------------------------------------------

        profile.coins -= bet_amount

        # Move wager into locked balance
        profile.locked_coins += bet_amount

        profile.save(
            update_fields=[
                "coins",
                "locked_coins",
            ]
        )

        # --------------------------------------------------
        # Ledger: Wager escrow
        # --------------------------------------------------

        SystemTransactionLog.objects.create(
            user_profile=profile,
            amount=-bet_amount,
            log_type="WAGER_ESCROW",
            reference_id=str(game_id),
        )

        # --------------------------------------------------
        # Add player to game
        # --------------------------------------------------

        game.players.add(profile)

        game.total_pool_escrow += bet_amount

        # --------------------------------------------------
        # Activate room when 2 players join
        # --------------------------------------------------

        if game.players.count() == 2:

            game.game_status = "ACTIVE"

            config = SystemConfiguration.get_solo()

            # ----------------------------------------------
            # Calculate platform fee
            # ----------------------------------------------

            game.service_fee_cut = int(
                (
                    game.total_pool_escrow
                    * config.platform_tax_percentage
                ) / 100
            )

            # ----------------------------------------------
            # Calculate winner payout
            # ----------------------------------------------

            game.winner_payout = (
                game.total_pool_escrow
                - game.service_fee_cut
            )

        game.save()

        # --------------------------------------------------
        # Return result
        # --------------------------------------------------

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
        }


# ==========================================================
# GAME WINNER PAYOUT SERVICE
# ==========================================================

def finalize_wager_game(
    game_id,
    winning_device_token,
):
    """
    Finalizes an ACTIVE wager game.

    Winner:
        Receives game.winner_payout.

    Platform:
        Receives game.service_fee_cut.

    Players:
        Have their locked wager released.

    The game row is locked using select_for_update()
    to prevent concurrent/double payout.
    """

    with transaction.atomic():

        # --------------------------------------------------
        # Lock game
        # --------------------------------------------------

        game = (
            GameRoom.objects
            .select_for_update()
            .filter(game_id=game_id)
            .first()
        )

        if not game:
            return {
                "status": "error",
                "message": "Game room not found.",
            }

        # --------------------------------------------------
        # Prevent double payout
        # --------------------------------------------------

        if game.game_status != "ACTIVE":
            return {
                "status": "error",
                "message": (
                    "Game has already been processed "
                    f"or is not active. "
                    f"Current status: {game.game_status}"
                ),
            }

        # --------------------------------------------------
        # Validate winner token
        # --------------------------------------------------

        if not winning_device_token:
            return {
                "status": "error",
                "message": "Winning device token is required.",
            }

        # --------------------------------------------------
        # Find winner
        # --------------------------------------------------

        winner = (
            game.players
            .select_for_update()
            .filter(
                device_token=winning_device_token
            )
            .first()
        )

        if not winner:
            return {
                "status": "error",
                "message": (
                    "Winning player is not a participant "
                    "of this game."
                ),
            }

        # --------------------------------------------------
        # Read stored payout values
        # --------------------------------------------------

        winner_payout = int(
            game.winner_payout or 0
        )

        service_fee = int(
            game.service_fee_cut or 0
        )

        total_pool = int(
            game.total_pool_escrow or 0
        )

        # --------------------------------------------------
        # Validate accounting
        # --------------------------------------------------

        if winner_payout < 0:
            return {
                "status": "error",
                "message": "Invalid winner payout.",
            }

        if service_fee < 0:
            return {
                "status": "error",
                "message": "Invalid platform fee.",
            }

        if winner_payout + service_fee != total_pool:
            return {
                "status": "error",
                "message": (
                    "Payout calculation mismatch. "
                    f"Pool={total_pool}, "
                    f"Winner payout={winner_payout}, "
                    f"Platform fee={service_fee}"
                ),
            }

        # --------------------------------------------------
        # Get all participants
        # --------------------------------------------------

        participants = list(
            game.players
            .select_for_update()
            .all()
        )

        if not participants:
            return {
                "status": "error",
                "message": "Game has no participants.",
            }

        # --------------------------------------------------
        # Verify locked balances BEFORE changing anything
        # --------------------------------------------------

        for player in participants:

            if player.locked_coins < game.bet_amount:

                return {
                    "status": "error",
                    "message": (
                        f"Invalid locked balance "
                        f"for player {player.device_token}."
                    ),
                }

        # --------------------------------------------------
        # Mark game completed
        # --------------------------------------------------

        game.game_status = "COMPLETED"

        game.save(
            update_fields=[
                "game_status",
            ]
        )

        # --------------------------------------------------
        # Release locked wagers
        # --------------------------------------------------

        for player in participants:

            player.locked_coins -= game.bet_amount

            # Winner receives payout
            if player.device_token == winning_device_token:
                player.coins += winner_payout

            player.save(
                update_fields=[
                    "coins",
                    "locked_coins",
                ]
            )

        # --------------------------------------------------
        # Winner ledger
        # --------------------------------------------------

        SystemTransactionLog.objects.create(
            user_profile=winner,
            amount=winner_payout,
            log_type="WAGER_PAYOUT",
            reference_id=str(game.game_id),
        )

        # --------------------------------------------------
        # Platform revenue
        # --------------------------------------------------

        admin_profile, _ = (
            UserProfileBalance.objects
            .select_for_update()
            .get_or_create(
                device_token="SYSTEM_PLATFORM_ADMIN_LEDGER"
            )
        )

        admin_profile.coins += service_fee

        admin_profile.save(
            update_fields=[
                "coins",
            ]
        )

        # --------------------------------------------------
        # Return result
        # --------------------------------------------------

        return {
            "status": "success",
            "message": (
                "Game payout completed successfully."
            ),
            "game_id": str(game.game_id),
            "winner": winning_device_token,
            "winner_payout": winner_payout,
            "service_fee": service_fee,
            "total_pool": total_pool,
        }


# ==========================================================
# BACKWARD-COMPATIBLE FINALIZE FUNCTION
# ==========================================================

def finalize_wager(game_id, winning_device_token):
    """
    Compatibility wrapper for views that import
    finalize_wager instead of finalize_wager_game.
    """

    return finalize_wager_game(
        game_id=game_id,
        winning_device_token=winning_device_token,
    )


# ==========================================================
# CANCEL WAGER SERVICE
# ==========================================================

def cancel_wager(game_id):
    """
    Cancels a wager game and restores each player's
    locked wager to their available balance.

    A game can only be cancelled once.
    """

    with transaction.atomic():

        # --------------------------------------------------
        # Lock game
        # --------------------------------------------------

        game = (
            GameRoom.objects
            .select_for_update()
            .filter(game_id=game_id)
            .first()
        )

        if not game:
            return {
                "status": "error",
                "message": "Game room not found.",
            }

        # --------------------------------------------------
        # Prevent duplicate cancellation
        # --------------------------------------------------

        if game.game_status in (
            "COMPLETED",
            "CANCELLED",
        ):
            return {
                "status": "error",
                "message": (
                    "Game has already been processed. "
                    f"Current status: {game.game_status}"
                ),
            }

        # --------------------------------------------------
        # Get participants
        # --------------------------------------------------

        participants = list(
            game.players
            .select_for_update()
            .all()
        )

        # --------------------------------------------------
        # Verify locked balances
        # --------------------------------------------------

        for player in participants:

            if player.locked_coins < game.bet_amount:

                return {
                    "status": "error",
                    "message": (
                        f"Invalid locked balance for "
                        f"player {player.device_token}."
                    ),
                }

        # --------------------------------------------------
        # Restore wagers
        # --------------------------------------------------

        for player in participants:

            player.locked_coins -= game.bet_amount
            player.coins += game.bet_amount

            player.save(
                update_fields=[
                    "coins",
                    "locked_coins",
                ]
            )

            # ----------------------------------------------
            # Refund ledger
            # ----------------------------------------------

            SystemTransactionLog.objects.create(
                user_profile=player,
                amount=game.bet_amount,
                log_type="WAGER_REFUND",
                reference_id=f"CANCEL_{game.game_id}",
            )

        # --------------------------------------------------
        # Mark game cancelled
        # --------------------------------------------------

        game.game_status = "CANCELLED"
        game.total_pool_escrow = 0

        game.save(
            update_fields=[
                "game_status",
                "total_pool_escrow",
            ]
        )

        # --------------------------------------------------
        # Return result
        # --------------------------------------------------

        return {
            "status": "success",
            "message": (
                "Wager cancelled and balances restored."
            ),
            "game_id": str(game.game_id),
            "players_refunded": len(participants),
        }


# ==========================================================
# WITHDRAWAL APPROVAL SERVICE
# ==========================================================

def process_withdrawal_approval(withdrawal_id):
    """
    Approves a pending withdrawal.

    Handles:
        - Withdrawal lookup
        - User balance locking
        - Insufficient balance protection
        - Balance deduction
        - Withdrawal approval
        - Withdrawal ledger entry
        - Referral commission
    """

    with transaction.atomic():

        # --------------------------------------------------
        # Lock withdrawal
        # --------------------------------------------------

        withdrawal = (
            WithdrawalRequest.objects
            .select_for_update()
            .filter(
                id=withdrawal_id,
                status="PENDING",
            )
            .first()
        )

        if not withdrawal:
            return {
                "status": "error",
                "message": (
                    "Pending withdrawal request "
                    "was not found."
                ),
            }

        # --------------------------------------------------
        # Lock user profile
        # --------------------------------------------------

        profile = (
            UserProfileBalance.objects
            .select_for_update()
            .filter(
                device_token=withdrawal.device_token
            )
            .first()
        )

        if not profile:
            return {
                "status": "error",
                "message": (
                    "User wallet profile not found."
                ),
            }

        # --------------------------------------------------
        # Verify balance
        # --------------------------------------------------

        if profile.coins < withdrawal.amount:

            return {
                "status": "error",
                "message": (
                    "Insufficient wallet balance."
                ),
            }

        # --------------------------------------------------
        # Deduct coins
        # --------------------------------------------------

        profile.coins -= withdrawal.amount

        profile.save(
            update_fields=[
                "coins",
            ]
        )

        # --------------------------------------------------
        # Approve withdrawal
        # --------------------------------------------------

        withdrawal.status = "APPROVED"

        withdrawal.save(
            update_fields=[
                "status",
            ]
        )

        # --------------------------------------------------
        # Withdrawal ledger
        # --------------------------------------------------

        SystemTransactionLog.objects.create(
            user_profile=profile,
            amount=withdrawal.amount,
            log_type="WITHDRAWAL",
            reference_id=str(withdrawal.id),
        )

        # --------------------------------------------------
        # Referral commission
        # --------------------------------------------------

        commission = 0

        try:

            config = SystemConfiguration.get_solo()

            referral_mapping = (
                ReferralSystem.objects
                .select_related("referrer")
                .select_for_update()
                .get(
                    referred_user=profile
                )
            )

            referrer = (
                UserProfileBalance.objects
                .select_for_update()
                .get(
                    id=referral_mapping.referrer.id
                )
            )

            commission = int(
                (
                    withdrawal.amount
                    * config.withdrawal_commission_percentage
                ) / 100
            )

            if commission > 0:

                # ------------------------------------------
                # Credit referrer
                # ------------------------------------------

                referrer.coins += commission

                referrer.save(
                    update_fields=[
                        "coins",
                    ]
                )

                # ------------------------------------------
                # Update referral totals
                # ------------------------------------------

                referral_mapping.total_commission_earned += (
                    commission
                )

                referral_mapping.save(
                    update_fields=[
                        "total_commission_earned",
                    ]
                )

                # ------------------------------------------
                # Referral ledger
                # ------------------------------------------

                SystemTransactionLog.objects.create(
                    user_profile=referrer,
                    amount=commission,
                    log_type="REFERRAL_COMMISSION",
                    reference_id=(
                        f"WD_REF_{withdrawal.id}"
                    ),
                )

        except ReferralSystem.DoesNotExist:
            pass

        # --------------------------------------------------
        # Return result
        # --------------------------------------------------

        return {
            "status": "success",
            "message": (
                "Withdrawal approved successfully."
            ),
            "withdrawal_id": withdrawal.id,
            "device_token": withdrawal.device_token,
            "amount": withdrawal.amount,
            "commission": commission,
            "remaining_balance": profile.coins,
        }