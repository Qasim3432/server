# views/admin_rewards.py

import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import (
    staff_member_required,
)
from django.db import transaction
from django.db.models import (
    Count,
    Q,
    Sum,
)
from django.shortcuts import redirect, render
from django.utils import timezone

from ..models import (
    GameHistory,
    LeaderboardReward,
    LeaderboardRewardClaim,
    SystemSetting,
    SystemTransactionLog,
    UserProfileBalance,
)

from ..currency_utils import format_dollar


# ==========================================================
# HELPERS
# ==========================================================

def _get_reward_amount(rank, period_type):
    """
    Fetch reward amount for a given rank and period
    from SystemSetting. Falls back to defaults.
    """

    if period_type == "weekly":
        defaults = {1: 1000, 2: 500, 3: 250}
    else:  # monthly
        defaults = {1: 5000, 2: 3000, 3: 1000}

    key = f"{period_type}_reward_{rank}"

    try:
        return int(
            SystemSetting.get_value(
                key,
                str(defaults[rank]),
            )
        )
    except (ValueError, TypeError, KeyError):
        return defaults.get(rank, 0)


def _local_now():
    return timezone.localtime(timezone.now())


# ==========================================================
# PREVIOUS PERIOD — This is what we distribute
#
# ✅ FIX (issue #9): Admin can no longer distribute the CURRENT
# period mid-week. Distribution only targets COMPLETED periods.
# ==========================================================

def _get_previous_period(period_type):
    now = _local_now()

    if period_type == "weekly":
        current_week_start = (
            now - timedelta(days=now.weekday())
        ).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        period_start = current_week_start - timedelta(days=7)
        period_end = current_week_start

        iso = period_start.isocalendar()
        period_key = f"{iso.year}-W{iso.week:02d}"

    else:  # monthly
        current_month_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        if current_month_start.month == 1:
            period_start = current_month_start.replace(
                year=current_month_start.year - 1,
                month=12,
            )
        else:
            period_start = current_month_start.replace(
                month=current_month_start.month - 1,
            )
        period_end = current_month_start

        period_key = f"{period_start.year}-{period_start.month:02d}"

    return period_key, period_start, period_end


# ==========================================================
# CURRENT PERIOD — For preview only
# ==========================================================

def _get_current_period(period_type):
    now = _local_now()

    if period_type == "weekly":
        iso = now.isocalendar()
        period_key = f"{iso.year}-W{iso.week:02d}"
        period_start = (
            now - timedelta(days=now.weekday())
        ).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        period_end = (
            period_start + timedelta(days=7)
        ).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
    else:
        period_key = f"{now.year}-{now.month:02d}"
        period_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        if now.month == 12:
            period_end = now.replace(
                year=now.year + 1, month=1, day=1,
                hour=0, minute=0, second=0, microsecond=0,
            )
        else:
            period_end = now.replace(
                month=now.month + 1, day=1,
                hour=0, minute=0, second=0, microsecond=0,
            )

    return period_key, period_start, period_end


# ==========================================================
# TOP PLAYERS
#
# ✅ FIX (issue #9): Same tiebreak ordering as leaderboard.py
# so displayed rank matches distribution rank.
# ==========================================================

_TOP_ORDER = ("-wins", "-earnings", "-games", "user_profile__device_token")


def _get_top_players(period_start, period_end, limit=3):

    qs = GameHistory.objects.filter(
        played_at__gte=period_start,
        played_at__lt=period_end,
    )

    agg = (
        qs.values("user_profile__device_token")
        .annotate(
            games=Count("id"),
            wins=Count("id", filter=Q(result="WON")),
            earnings=Sum("coins_change"),
        )
        .filter(games__gt=0)
        .order_by(*_TOP_ORDER)[:limit]
    )

    tokens = [
        row["user_profile__device_token"]
        for row in agg
    ]

    profiles = {
        p.device_token: p
        for p in UserProfileBalance.objects.filter(
            device_token__in=tokens
        )
    }

    results = []

    for idx, row in enumerate(agg):

        token = row["user_profile__device_token"]
        profile = profiles.get(token)

        results.append({
            "rank": idx + 1,
            "device_token": token,
            "name": (
                profile.nickname
                if profile and profile.nickname
                else "Player"
            ),
            "wins": row["wins"] or 0,
            "games": row["games"] or 0,
            "earnings": format_dollar(row["earnings"] or 0),
            "profile_obj": profile,
        })

    return results


def _already_distributed(period_key):
    return (
        LeaderboardReward.objects
        .filter(period_key=period_key)
        .exists()
    )


# ==========================================================
# DASHBOARD — Shows PREVIOUS (distributable) period
# + CURRENT (preview) period
# ==========================================================

@staff_member_required
def leaderboard_rewards_dashboard(request):

    # ----------------------------------------------
    # PREVIOUS week — distributable
    # ----------------------------------------------

    prev_week_key, prev_week_start, prev_week_end = (
        _get_previous_period("weekly")
    )

    prev_week_top = _get_top_players(
        prev_week_start,
        prev_week_end,
    )

    prev_week_prizes_raw = {
        1: _get_reward_amount(1, "weekly"),
        2: _get_reward_amount(2, "weekly"),
        3: _get_reward_amount(3, "weekly"),
    }

    prev_week_prizes = {
        k: format_dollar(v) for k, v in prev_week_prizes_raw.items()
    }

    prev_week_total_raw = sum(prev_week_prizes_raw.values())
    prev_week_total = format_dollar(prev_week_total_raw)

    prev_week_distributed = _already_distributed(prev_week_key)

    # ----------------------------------------------
    # CURRENT week — preview only (not distributable)
    # ----------------------------------------------

    cur_week_key, cur_week_start, cur_week_end = (
        _get_current_period("weekly")
    )

    cur_week_top = _get_top_players(
        cur_week_start,
        cur_week_end,
    )

    # ----------------------------------------------
    # PREVIOUS month — distributable
    # ----------------------------------------------

    prev_month_key, prev_month_start, prev_month_end = (
        _get_previous_period("monthly")
    )

    prev_month_top = _get_top_players(
        prev_month_start,
        prev_month_end,
    )

    prev_month_prizes_raw = {
        1: _get_reward_amount(1, "monthly"),
        2: _get_reward_amount(2, "monthly"),
        3: _get_reward_amount(3, "monthly"),
    }

    prev_month_prizes = {
        k: format_dollar(v) for k, v in prev_month_prizes_raw.items()
    }

    prev_month_total_raw = sum(prev_month_prizes_raw.values())
    prev_month_total = format_dollar(prev_month_total_raw)

    prev_month_distributed = _already_distributed(prev_month_key)

    # ----------------------------------------------
    # CURRENT month — preview only
    # ----------------------------------------------

    cur_month_key, cur_month_start, cur_month_end = (
        _get_current_period("monthly")
    )

    cur_month_top = _get_top_players(
        cur_month_start,
        cur_month_end,
    )

    # ----------------------------------------------
    # Distribution history
    # ----------------------------------------------

    history = (
        LeaderboardReward.objects
        .all()
        .order_by("-distributed_at")[:20]
    )

    history_list = []

    for h in history:

        winners = []

        try:
            winners = json.loads(h.winners_json or "[]")
        except Exception:
            pass

        history_list.append({
            "period_type": h.period_type,
            "period_key": h.period_key,
            "distributed_at": h.distributed_at.strftime(
                "%d %b %Y, %I:%M %p"
            ),
            "total_amount": format_dollar(h.total_amount),
            "winners": winners,
        })

    context = {

        # ✅ Previous period — distributable
        "weekly": {
            "period_key": prev_week_key,
            "period_start": prev_week_start.strftime("%d %b %Y"),
            "period_end": prev_week_end.strftime("%d %b %Y"),
            "top_players": prev_week_top,
            "prizes": prev_week_prizes,
            "total": prev_week_total,
            "already_distributed": prev_week_distributed,
        },

        # ✅ Current period — preview only
        "weekly_current": {
            "period_key": cur_week_key,
            "period_start": cur_week_start.strftime("%d %b %Y"),
            "period_end": cur_week_end.strftime("%d %b %Y"),
            "top_players": cur_week_top,
        },

        "monthly": {
            "period_key": prev_month_key,
            "period_start": prev_month_start.strftime("%d %b %Y"),
            "period_end": prev_month_end.strftime("%d %b %Y"),
            "top_players": prev_month_top,
            "prizes": prev_month_prizes,
            "total": prev_month_total,
            "already_distributed": prev_month_distributed,
        },

        "monthly_current": {
            "period_key": cur_month_key,
            "period_start": cur_month_start.strftime("%d %b %Y"),
            "period_end": cur_month_end.strftime("%d %b %Y"),
            "top_players": cur_month_top,
        },

        "history": history_list,
    }

    return render(
        request,
        "admin_rewards.html",
        context,
    )


# ==========================================================
# DISTRIBUTE — WEEKLY
# ==========================================================

@staff_member_required
def distribute_weekly_rewards(request):
    return _distribute(request, "weekly")


# ==========================================================
# DISTRIBUTE — MONTHLY
# ==========================================================

@staff_member_required
def distribute_monthly_rewards(request):
    return _distribute(request, "monthly")


# ==========================================================
# CORE DISTRIBUTION — PREVIOUS period only
# ==========================================================

def _distribute(request, period_type):

    if request.method != "POST":
        return redirect("leaderboard_rewards_dashboard")

    # ✅ FIX: distribute PREVIOUS period (already ended)
    period_key, period_start, period_end = (
        _get_previous_period(period_type)
    )

    if _already_distributed(period_key):
        messages.warning(
            request,
            (
                f"Rewards for {period_key} "
                f"have already been distributed."
            ),
        )
        return redirect("leaderboard_rewards_dashboard")

    top_players = _get_top_players(
        period_start,
        period_end,
        limit=3,
    )

    if not top_players:
        messages.error(
            request,
            (
                f"No players found for {period_key}. "
                f"Nothing to distribute."
            ),
        )
        return redirect("leaderboard_rewards_dashboard")

    prizes = {
        1: _get_reward_amount(1, period_type),
        2: _get_reward_amount(2, period_type),
        3: _get_reward_amount(3, period_type),
    }

    total_pending = 0
    winners_snapshot = []

    with transaction.atomic():

        for player in top_players:

            rank = player["rank"]
            reward = prizes.get(rank, 0)

            if reward <= 0:
                continue

            profile = (
                UserProfileBalance.objects
                .select_for_update()
                .filter(id=player["profile_obj"].id)
                .first()
            )

            if not profile:
                continue

            claim, created = (
                LeaderboardRewardClaim.objects
                .get_or_create(
                    user_profile=profile,
                    period_key=period_key,
                    defaults={
                        "amount": reward,
                        "rank": rank,
                        "period_type": period_type,
                        "is_claimed": False,
                    },
                )
            )

            if not created:
                print(
                    f"⚠️ CLAIM EXISTS | "
                    f"{period_type} {period_key} | "
                    f"Rank #{rank} | {profile.device_token}"
                )
                continue

            total_pending += reward

            winners_snapshot.append({
                "rank": rank,
                "device_token": profile.device_token,
                "name": player["name"],
                "wins": player["wins"],
                "reward": format_dollar(reward),
                "claim_id": claim.id,
            })

            print(
                f"🎁 CLAIM CREATED | "
                f"{period_type} {period_key} | "
                f"Rank #{rank} | "
                f"{profile.device_token} | "
                f"+{format_dollar(reward)} (pending)"
            )

        LeaderboardReward.objects.create(
            period_type=period_type,
            period_key=period_key,
            period_start=period_start,
            period_end=period_end,
            distributed_by=request.user.username,
            total_amount=total_pending,
            winners_json=json.dumps(winners_snapshot),
        )

    messages.success(
        request,
        (
            f"✅ {period_type.title()} reward claims "
            f"created for {period_key}. "
            f"Total: {format_dollar(total_pending)} pending "
            f"for {len(winners_snapshot)} players. "
            f"Users will collect manually."
        ),
    )

    return redirect("leaderboard_rewards_dashboard")