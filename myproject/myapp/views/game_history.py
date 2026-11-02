# views/game_history.py

from django.db.models import Count, Q
from django.http import JsonResponse

from ..models import GameHistory, UserProfileBalance
from ..decorators import require_device_owner


# Results jo loss count hote hain
LOSS_RESULTS = ["LOST", "SURRENDERED"]


# ==========================================================
# ✅ FIX: @require_device_owner
#
# Pehle koi bhi logged-in user kisi ka bhi game history
# fetch kar sakta tha sirf device_token pata hone pe.
# Ab X-Auth-Token owner aur URL device_token match hone chahiye.
# ==========================================================

@require_device_owner
def get_game_history(request, device_token):

    profile = (
        UserProfileBalance.objects
        .filter(device_token=device_token)
        .first()
    )

    if not profile:
        return JsonResponse(
            {"status": "error", "message": "Profile not found."},
            status=404,
        )

    try:
        limit = int(request.GET.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50

    limit = max(1, min(limit, 200))

    # ==================================================
    # Base queryset
    # ==================================================
    base_qs = GameHistory.objects.filter(user_profile=profile)

    # ==================================================
    # Stats — single aggregation query (optimized)
    # ==================================================
    stats = base_qs.aggregate(
        total_games=Count("id"),
        total_wins=Count("id", filter=Q(result="WON")),
        total_losses=Count("id", filter=Q(result__in=LOSS_RESULTS)),
        total_cancelled=Count("id", filter=Q(result="CANCELLED")),
        total_surrendered=Count("id", filter=Q(result="SURRENDERED")),
    )

    total_games = stats["total_games"] or 0
    total_wins = stats["total_wins"] or 0
    total_losses = stats["total_losses"] or 0
    total_cancelled = stats["total_cancelled"] or 0
    total_surrendered = stats["total_surrendered"] or 0

    # Win rate — only counts WON vs (WON + LOST + SURRENDERED)
    # CANCELLED ko exclude karo (refunded hote hain)
    decided_games = total_wins + total_losses

    win_rate = (
        round((total_wins / decided_games) * 100, 1)
        if decided_games > 0
        else 0.0
    )

    # ==================================================
    # Fetch entries
    # ==================================================
    entries = base_qs.order_by("-played_at")[:limit]

    history_payload = []

    for entry in entries:
        history_payload.append({
            "game_id": entry.game_id,
            "bet_amount": entry.bet_amount,
            "result": entry.result,
            "coins_change": entry.coins_change,
            "game_mode": entry.game_mode,
            "opponent_count": entry.opponent_count,
            "played_at": entry.played_at.strftime("%d %b %Y, %I:%M %p"),
        })

    return JsonResponse({
        "status": "success",
        "stats": {
            "total_games": total_games,
            "total_wins": total_wins,
            "total_losses": total_losses,
            "total_cancelled": total_cancelled,
            "total_surrendered": total_surrendered,
            "win_rate": win_rate,
        },
        "history": history_payload,
    })