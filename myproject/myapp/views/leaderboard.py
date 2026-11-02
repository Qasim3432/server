# views/leaderboard.py

import json

from datetime import timedelta

from django.db import transaction
from django.db.models import (
    Count,
    Q,
    Sum,
)
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from ..models import (
    GameHistory,
    LeaderboardRewardClaim,
    SystemTransactionLog,
    UserProfileBalance,
)


LOSS_RESULTS = ["LOST", "SURRENDERED"]

# Consistent tiebreak ordering for top_players + my_rank
# matches admin_rewards.py exactly.
_TOP_ORDER = ("-wins", "-earnings", "-games", "user_profile__device_token")


# ==========================================================
# PERIOD HELPERS — Calendar-based, local timezone
#
# ✅ FIX (issue #17, #18):
#   - Boundaries now use timezone.localtime() so weekly/monthly
#     boundaries land on the server's calendar midnight, not UTC.
#   - With TIME_ZONE = Asia/Karachi, Pakistani users see correct
#     Monday/month-start boundaries.
# ==========================================================

def _local_now():
    return timezone.localtime(timezone.now())


def _get_period_start(period):
    """
    weekly  → Monday 00:00 local
    monthly → 1st of month 00:00 local
    alltime → None
    """
    now = _local_now()

    if period == "weekly":
        return (
            now - timedelta(days=now.weekday())
        ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    if period == "monthly":
        return now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    return None


def _get_period_end(period):
    """
    weekly  → Next Monday 00:00 local
    monthly → 1st of next month 00:00 local
    alltime → None
    """
    now = _local_now()

    if period == "weekly":
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return (
            now + timedelta(days=days_until_monday)
        ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    if period == "monthly":
        if now.month == 12:
            return now.replace(
                year=now.year + 1,
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        return now.replace(
            month=now.month + 1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    return None


# ==========================================================
# LEADERBOARD
# ==========================================================

def get_leaderboard(request):

    period = str(
        request.GET.get("period", "alltime")
    ).lower()

    if period not in ("weekly", "monthly", "alltime"):
        period = "alltime"

    try:
        limit = int(request.GET.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50

    limit = max(1, min(limit, 100))

    my_device_token = str(
        request.GET.get("device_token", "")
    ).strip()

    qs = GameHistory.objects.all()

    start_date = _get_period_start(period)

    if start_date:
        qs = qs.filter(played_at__gte=start_date)

    def _aggregate(qs_inner):
        return (
            qs_inner.values("user_profile__device_token")
            .annotate(
                games=Count("id"),
                wins=Count("id", filter=Q(result="WON")),
                losses=Count("id", filter=Q(result__in=LOSS_RESULTS)),
                earnings=Sum("coins_change"),
            )
            .filter(games__gt=0)
        )

    # Top players
    agg = _aggregate(qs)

    agg_list = list(
        agg.order_by(*_TOP_ORDER)[:limit]
    )

    tokens = [
        row["user_profile__device_token"]
        for row in agg_list
    ]

    profiles = {
        p.device_token: p
        for p in UserProfileBalance.objects.filter(
            device_token__in=tokens
        )
    }

    top_players = []

    for idx, row in enumerate(agg_list):

        token = row["user_profile__device_token"]
        profile = profiles.get(token)

        display_name = (
            profile.nickname
            if profile and profile.nickname
            else "Player"
        )

        pic_url = None
        if profile and profile.profile_pic:
            try:
                pic_url = profile.profile_pic.url
            except Exception:
                pic_url = None

        wins = row["wins"] or 0
        games = row["games"] or 0

        win_rate = (
            round((wins / games) * 100, 1)
            if games > 0
            else 0.0
        )

        top_players.append({
            "rank": idx + 1,
            "device_token": token,
            "display_name": display_name,
            "profile_pic": pic_url,
            "wins": wins,
            "games": games,
            "losses": row["losses"] or 0,
            "earnings": row["earnings"] or 0,
            "win_rate": win_rate,
        })

    # ==========================================================
    # My rank
    #
    # ✅ FIX (issue #18): Tiebreak now includes device_token
    # (alphabetical ascending) so ranks are deterministic and
    # consistent with top_players ordering.
    # ==========================================================

    my_rank_data = None

    if my_device_token:

        my_row = (
            _aggregate(qs)
            .filter(
                user_profile__device_token=my_device_token
            )
            .order_by(*_TOP_ORDER)
            .first()
        )

        if my_row:

            my_wins = my_row["wins"] or 0
            my_games = my_row["games"] or 0
            my_losses = my_row["losses"] or 0
            my_earnings = my_row["earnings"] or 0

            better_count = (
                _aggregate(qs)
                .filter(
                    Q(wins__gt=my_wins)
                    | (
                        Q(wins=my_wins)
                        & Q(earnings__gt=my_earnings)
                    )
                    | (
                        Q(wins=my_wins)
                        & Q(earnings=my_earnings)
                        & Q(games__gt=my_games)
                    )
                    | (
                        Q(wins=my_wins)
                        & Q(earnings=my_earnings)
                        & Q(games=my_games)
                        & Q(user_profile__device_token__lt=my_device_token)
                    )
                )
                .count()
            )

            my_rank = better_count + 1

            my_win_rate = (
                round((my_wins / my_games) * 100, 1)
                if my_games > 0
                else 0.0
            )

            my_rank_data = {
                "rank": my_rank,
                "device_token": my_device_token,
                "wins": my_wins,
                "games": my_games,
                "losses": my_losses,
                "earnings": my_earnings,
                "win_rate": my_win_rate,
            }

    # Pending rewards
    pending_rewards = []

    if my_device_token:

        profile = UserProfileBalance.objects.filter(
            device_token=my_device_token
        ).first()

        if profile:
            claims = LeaderboardRewardClaim.objects.filter(
                user_profile=profile,
                is_claimed=False,
            )

            for c in claims:
                pending_rewards.append({
                    "id": c.id,
                    "amount": c.amount,
                    "rank": c.rank,
                    "period_type": c.period_type,
                    "period_key": c.period_key,
                    "created_at": c.created_at.isoformat(),
                })

    # Period countdown for client
    period_end = _get_period_end(period)

    return JsonResponse({
        "status": "success",
        "period": period,
        "period_ends_at": (
            period_end.isoformat()
            if period_end is not None
            else None
        ),
        "top_players": top_players,
        "my_rank": my_rank_data,
        "pending_rewards": pending_rewards,
    })


# ==========================================================
# GET MY PENDING REWARDS
# ==========================================================

def get_my_pending_rewards(request):

    my_device_token = str(
        request.GET.get("device_token", "")
    ).strip()

    if not my_device_token:
        return JsonResponse(
            {
                "status": "error",
                "message": "device_token required",
            },
            status=400,
        )

    profile = UserProfileBalance.objects.filter(
        device_token=my_device_token
    ).first()

    if not profile:
        return JsonResponse({
            "status": "success",
            "total_amount": 0,
            "claims": [],
        })

    claims = LeaderboardRewardClaim.objects.filter(
        user_profile=profile,
        is_claimed=False,
    )

    total = (
        claims.aggregate(total=Sum("amount"))["total"]
        or 0
    )

    claims_list = [
        {
            "id": c.id,
            "amount": c.amount,
            "rank": c.rank,
            "period_type": c.period_type,
            "period_key": c.period_key,
            "created_at": c.created_at.isoformat(),
        }
        for c in claims
    ]

    return JsonResponse({
        "status": "success",
        "total_amount": total,
        "claims": claims_list,
    })


# ==========================================================
# CLAIM REWARD
# ==========================================================

@csrf_exempt
@transaction.atomic
def claim_leaderboard_reward(request):

    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "POST required"},
            status=405,
        )

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON"},
            status=400,
        )

    device_token = str(
        data.get("device_token", "")
    ).strip()

    claim_id = data.get("claim_id")

    if not device_token or not claim_id:
        return JsonResponse(
            {
                "status": "error",
                "message": "device_token aur claim_id required",
            },
            status=400,
        )

    profile = (
        UserProfileBalance.objects
        .select_for_update()
        .filter(device_token=device_token)
        .first()
    )

    if not profile:
        return JsonResponse(
            {"status": "error", "message": "User not found"},
            status=404,
        )

    claim = (
        LeaderboardRewardClaim.objects
        .select_for_update()
        .filter(
            id=claim_id,
            user_profile=profile,
        )
        .first()
    )

    if not claim:
        return JsonResponse(
            {"status": "error", "message": "Claim not found"},
            status=404,
        )

    if claim.is_claimed:
        return JsonResponse(
            {"status": "error", "message": "Already claimed"},
            status=400,
        )

    profile.coins += claim.amount
    profile.save(update_fields=["coins"])

    claim.is_claimed = True
    claim.claimed_at = timezone.now()
    claim.save(update_fields=["is_claimed", "claimed_at"])

    SystemTransactionLog.objects.create(
        user_profile=profile,
        amount=claim.amount,
        log_type="LEADERBOARD_REWARD",
        reference_id=f"{claim.period_key}_rank{claim.rank}",
    )

    print(
        f"🎁 REWARD CLAIMED | "
        f"user={device_token} | "
        f"amount={claim.amount} | "
        f"period={claim.period_key} | "
        f"new_balance={profile.coins}"
    )

    return JsonResponse({
        "status": "success",
        "amount": claim.amount,
        "new_balance": profile.coins,
        "message": f"🎉 {claim.amount} coins claimed!",
    })