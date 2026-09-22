from django.shortcuts import (
    render,
    redirect,
)

from ..models import SystemSetting

# ==========================================
# GIFT CONTROL DASHBOARD
# ==========================================

def gift_control_dashboard(request):

    if request.method == "POST":

        gift_enabled = request.POST.get(
            "gift_enabled",
            "1",
        )

        paid_spin_cost = request.POST.get(
            "paid_spin_cost",
            "40",
        )

        SystemSetting.objects.update_or_create(
            key="gift_enabled",
            defaults={
                "value": gift_enabled,
            },
        )

        SystemSetting.objects.update_or_create(
            key="paid_spin_cost",
            defaults={
                "value": paid_spin_cost,
            },
        )

        return redirect(
            "gift_control_dashboard"
        )

    gift_enabled = SystemSetting.get_value(
        "gift_enabled",
        "1",
    )

    paid_spin_cost = SystemSetting.get_value(
        "paid_spin_cost",
        "40",
    )

    return render(
        request,
        "gift_control.html",
        {
            "gift_enabled": gift_enabled,
            "paid_spin_cost": paid_spin_cost,
        },
    )
    