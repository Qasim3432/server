from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from ..models import SystemSetting

@staff_member_required
def gift_control_dashboard(request):

    if request.method == "POST":
        gift_enabled = request.POST.get("gift_enabled", "1")
        paid_spin_cost_dollars = request.POST.get("paid_spin_cost", "0.40")
        
        # ✅ Safe conversion from Dollars to Cents
        try:
            if not paid_spin_cost_dollars or str(paid_spin_cost_dollars).strip() == "":
                paid_spin_cost_dollars = "0.40"
            paid_spin_cost_cents = int(float(paid_spin_cost_dollars) * 100)
        except (ValueError, TypeError):
            paid_spin_cost_cents = 40

        SystemSetting.objects.update_or_create(
            key="gift_enabled",
            defaults={"value": gift_enabled},
        )
        SystemSetting.objects.update_or_create(
            key="paid_spin_cost",
            defaults={"value": str(paid_spin_cost_cents)},
        )

        return redirect("gift_control_dashboard")

    gift_enabled = SystemSetting.get_value("gift_enabled", "1")
    
    # ✅ Safe conversion from Cents to Dollars for display
    paid_spin_cost_str = SystemSetting.get_value("paid_spin_cost", "40")
    try:
        if not paid_spin_cost_str or str(paid_spin_cost_str).strip() == "":
            paid_spin_cost_cents = 40
        else:
            paid_spin_cost_cents = int(paid_spin_cost_str)
    except (ValueError, TypeError):
        paid_spin_cost_cents = 40

    paid_spin_cost_display = f"{paid_spin_cost_cents / 100:.2f}"

    return render(
        request,
        "gift_control.html",
        {
            "gift_enabled": gift_enabled,
            "paid_spin_cost": paid_spin_cost_display,
        },
    )