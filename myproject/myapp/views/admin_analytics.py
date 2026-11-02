# myapp/views/admin_analytics.py

from datetime import timedelta
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from ..models import GameRoom, SystemTransactionLog, UserProfileBalance
from ..currency_utils import format_dollar # ✅ Import


def _sum_ledger(log_types, since, sign_negative=False):
    qs = SystemTransactionLog.objects.filter(log_type__in=log_types, timestamp__gte=since)
    total = qs.aggregate(total=Sum("amount"))["total"] or 0
    return abs(total) if sign_negative else total


@staff_member_required
def analytics_dashboard(request):
    now = timezone.now()
    period = request.GET.get("period", "24h")

    if period == "7d":
        since = now - timedelta(days=7); period_label = "Last 7 Days"
    elif period == "30d":
        since = now - timedelta(days=30); period_label = "Last 30 Days"
    else:
        period = "24h"; since = now - timedelta(hours=24); period_label = "Last 24 Hours"

    total_in = _sum_ledger(["DEPOSIT"], since)
    total_out = _sum_ledger(["WITHDRAWAL"], since, sign_negative=True)
    wager_fees = GameRoom.objects.filter(game_status="COMPLETED", updated_at__gte=since).aggregate(total=Sum("service_fee_cut"))["total"] or 0
    spin_costs = _sum_ledger(["SPIN_COST"], since, sign_negative=True)
    
    platform_earnings = wager_fees + spin_costs

    games_count = GameRoom.objects.filter(game_status="COMPLETED", updated_at__gte=since).count()
    wager_volume = GameRoom.objects.filter(game_status="COMPLETED", updated_at__gte=since).aggregate(total=Sum("total_pool_escrow"))["total"] or 0

    total_payout = _sum_ledger(["WAGER_PAYOUT"], since)
    total_refunds = _sum_ledger(["WAGER_REFUND"], since)
    total_referral_bonus = _sum_ledger(["REFERRAL_BONUS"], since)
    total_referral_commission = _sum_ledger(["REFERRAL_COMMISSION"], since)
    total_referral_invite_reward = _sum_ledger(["REFERRAL_INVITE_REWARD"], since)
    total_spin_rewards = _sum_ledger(["SPIN_REWARD"], since)

    hourly_data = []
    if period == "24h":
        for i in range(23, -1, -1):
            b_start = now - timedelta(hours=i + 1); b_end = now - timedelta(hours=i)
            hourly_data.append({
                "hour": b_start.strftime("%H:00"),
                "in": SystemTransactionLog.objects.filter(log_type="DEPOSIT", timestamp__gte=b_start, timestamp__lt=b_end).aggregate(total=Sum("amount"))["total"] or 0,
                "out": abs(SystemTransactionLog.objects.filter(log_type="WITHDRAWAL", timestamp__gte=b_start, timestamp__lt=b_end).aggregate(total=Sum("amount"))["total"] or 0),
                "games": GameRoom.objects.filter(game_status="COMPLETED", updated_at__gte=b_start, updated_at__lt=b_end).count(),
            })
    
    # Format hourly data for template
    hourly_data_formatted = [
        {
            "hour": h["hour"],
            "in": format_dollar(h["in"]),
            "out": format_dollar(h["out"]),
            "games": h["games"]
        } for h in hourly_data
    ]

    recent_logs = SystemTransactionLog.objects.filter(timestamp__gte=since).select_related("user_profile").order_by("-timestamp")[:30]
    recent_transactions = [{
        "device_token": log.user_profile.device_token, "nickname": log.user_profile.nickname or "—",
        "log_type": log.log_type, "amount": format_dollar(log.amount), "reference_id": log.reference_id, # ✅ Format
        "time": log.timestamp.strftime("%d %b, %I:%M %p"),
    } for log in recent_logs]

    context = {
        "period": period, "period_label": period_label,
        "since": since.strftime("%d %b %Y, %I:%M %p"), "now": now.strftime("%d %b %Y, %I:%M %p"),
        "summary": {
            "total_in": format_dollar(total_in), 
            "total_out": format_dollar(total_out), 
            "net_flow": format_dollar(total_in - total_out),
            "platform_earnings": format_dollar(platform_earnings), 
            "wager_fees": format_dollar(wager_fees), 
            "spin_costs": format_dollar(spin_costs),
            "games_count": games_count, 
            "wager_volume": format_dollar(wager_volume), 
            "total_payout": format_dollar(total_payout),
            "total_refunds": format_dollar(total_refunds), 
            "total_referral_bonus": format_dollar(total_referral_bonus),
            "total_referral_commission": format_dollar(total_referral_commission), 
            "total_referral_invite_reward": format_dollar(total_referral_invite_reward),
            "total_spin_rewards": format_dollar(total_spin_rewards),
        },
        "hourly_data": hourly_data_formatted, "recent_transactions": recent_transactions,
    }
    return render(request, "admin_analytics.html", context)