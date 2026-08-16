from django.contrib import messages
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from ..models import (
    SystemPaymentMethod,
    DepositRequest,
    WithdrawalRequest,
    UserProfileBalance,
    SystemConfiguration,
)


# ==========================================
# ADMIN MAIN PORTAL
# ==========================================

def custom_admin_main_portal(request):

    pending_deposits_count = (
        DepositRequest.objects
        .filter(status="PENDING")
        .count()
    )

    pending_withdrawals_count = (
        WithdrawalRequest.objects
        .filter(status="PENDING")
        .count()
    )

    active_methods_count = (
        SystemPaymentMethod.objects
        .filter(is_active=True)
        .count()
    )

    return render(
        request,
        "admin_main_portal.html",
        {
            "pending_deposits_count":
                pending_deposits_count,
            "pending_withdrawals_count":
                pending_withdrawals_count,
            "active_methods_count":
                active_methods_count,
        },
    )


# ==========================================
# PAYMENT SETTINGS
# ==========================================

def custom_admin_settings(request):

    methods = (
        SystemPaymentMethod.objects
        .all()
    )

    if request.method == "POST":

        method_id = request.POST.get(
            "method_id"
        )

        method_instance = get_object_or_404(
            SystemPaymentMethod,
            id=method_id,
        )

        method_instance.account_name = (
            request.POST.get("account_name")
        )

        method_instance.account_number = (
            request.POST.get("account_number")
        )

        method_instance.is_active = (
            "is_active" in request.POST
        )

        method_instance.save()

        messages.success(
            request,
            (
                f"Updated details for "
                f"{method_instance.get_method_type_display()}!"
            ),
        )

        return redirect(
            "custom_admin_settings"
        )

    return render(
        request,
        "admin_settings.html",
        {
            "methods": methods
        },
    )


# ==========================================
# FINANCE MANAGEMENT
# ==========================================

def finance_management_dashboard(request):

    config = SystemConfiguration.get_solo()

    if request.method == "POST":

        withdrawal_commission = (
            request.POST.get(
                "withdrawal_commission"
            )
        )

        platform_tax = (
            request.POST.get(
                "platform_tax"
            )
        )

        winner_payout = (
            request.POST.get(
                "winner_payout"
            )
        )

        try:

            withdrawal_commission = int(
                withdrawal_commission
            )

            platform_tax = int(
                platform_tax
            )

            winner_payout = int(
                winner_payout
            )

            if (
                platform_tax
                + winner_payout
                != 100
            ):
                messages.error(
                    request,
                    (
                        "Configuration Check Failed: "
                        "Platform Tax + Winner Payout "
                        "shares must sum to exactly 100%."
                    ),
                )

            elif not 0 <= withdrawal_commission <= 100:
                messages.error(
                    request,
                    (
                        "Withdrawal commission must "
                        "be between 0 and 100."
                    ),
                )

            elif not 0 <= platform_tax <= 100:
                messages.error(
                    request,
                    (
                        "Platform tax must be "
                        "between 0 and 100."
                    ),
                )

            else:

                config.withdrawal_commission_percentage = (
                    withdrawal_commission
                )

                config.platform_tax_percentage = (
                    platform_tax
                )

                config.winner_payout_percentage = (
                    winner_payout
                )

                config.save()

                messages.success(
                    request,
                    (
                        "System Matrix parameters "
                        "applied successfully."
                    ),
                )

        except (
            ValueError,
            TypeError,
        ):
            messages.error(
                request,
                (
                    "Invalid entries. Parameters "
                    "must be integers."
                ),
            )

        return redirect(
            "finance_management_dashboard"
        )

    # ======================================
    # BOOKKEEPING
    # ======================================

    total_credited = (
        DepositRequest.objects
        .filter(status="APPROVED")
        .aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )

    total_debited = (
        WithdrawalRequest.objects
        .filter(status="APPROVED")
        .aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )

    admin_profile = (
        UserProfileBalance.objects
        .filter(
            device_token="SYSTEM_PLATFORM_ADMIN_LEDGER"
        )
        .first()
    )

    revenue_earned = (
        admin_profile.coins
        if admin_profile
        else 0
    )

    normal_profiles = (
        UserProfileBalance.objects
        .exclude(
            device_token="SYSTEM_PLATFORM_ADMIN_LEDGER"
        )
    )

    liquid_supply = (
        normal_profiles
        .aggregate(
            total=Sum("coins")
        )["total"]
        or 0
    )

    locked_escrow = (
        normal_profiles
        .aggregate(
            total=Sum("locked_coins")
        )["total"]
        or 0
    )

    total_liability = (
        liquid_supply
        + locked_escrow
    )

    context = {
        "config": config,

        "metrics": {
            "total_credited_inflow":
                total_credited,

            "total_debited_outflow":
                total_debited,

            "total_revenue_earned":
                revenue_earned,

            "total_system_liability":
                total_liability,
        },

        "breakdown": {
            "approved_deposits":
                total_credited,

            "issued_bonuses":
                0,

            "liquid_supply":
                liquid_supply,

            "locked_escrow":
                locked_escrow,
        },
    }

    return render(
        request,
        "dashboard/finance_management.html",
        context,
    )