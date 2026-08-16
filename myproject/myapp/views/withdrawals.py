import json

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.csrf import csrf_exempt

from ..models import (
    WithdrawalRequest,
    UserProfileBalance,
)

from ..services.wager_service import (
    process_withdrawal_approval,
)


# ==========================================
# MOBILE WITHDRAWAL
# ==========================================

@csrf_exempt
def submit_withdrawal_request(request):

    if request.method != "POST":
        return JsonResponse(
            {"error": "POST required"},
            status=405,
        )

    try:
        data = json.loads(request.body)

        device_token = data.get("device_token")
        amount = int(data.get("amount", 0))
        method = data.get("method")
        account_title = data.get("account_title")
        account_number = data.get("account_number")

        if not all([
            device_token,
            amount > 0,
            method,
            account_title,
            account_number,
        ]):
            return JsonResponse(
                {
                    "error": (
                        "Invalid fields "
                        "verification failure"
                    )
                },
                status=400,
            )

        profile, _ = (
            UserProfileBalance.objects
            .get_or_create(
                device_token=device_token
            )
        )

        if profile.coins < amount:
            return JsonResponse(
                {
                    "error": (
                        "Insufficient wallet balance "
                        "to request withdrawal"
                    )
                },
                status=400,
            )

        WithdrawalRequest.objects.create(
            device_token=device_token,
            amount=amount,
            method=method,
            account_title=account_title,
            account_number=account_number,
            status="PENDING",
        )

        return JsonResponse({
            "status": "success",
            "message": (
                "Withdrawal request logged successfully!"
            ),
        })

    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ):
        return JsonResponse(
            {
                "error": "Invalid request payload."
            },
            status=400,
        )

    except Exception as exc:
        return JsonResponse(
            {"error": str(exc)},
            status=400,
        )


# ==========================================
# ADMIN WITHDRAWAL DASHBOARD
# ==========================================

def custom_withdrawal_dashboard(request):

    withdrawals = (
        WithdrawalRequest.objects
        .all()
        .order_by("-created_at")
    )

    withdrawal_items = []

    for withdrawal in withdrawals:

        profile, _ = (
            UserProfileBalance.objects
            .get_or_create(
                device_token=withdrawal.device_token
            )
        )

        withdrawal_items.append({
            "request": withdrawal,
            "current_balance": profile.coins,
            "has_enough": (
                profile.coins >= withdrawal.amount
            ),
        })

    context = {
        "withdrawal_items": withdrawal_items
    }

    if (
        request.method == "GET"
        and request.headers.get(
            "x-requested-with"
        ) == "XMLHttpRequest"
    ):
        return render(
            request,
            "withdrawal_table_partial.html",
            context,
        )

    return render(
        request,
        "withdrawal_change_form.html",
        context,
    )


# ==========================================
# APPROVE WITHDRAWAL
# ==========================================

@csrf_exempt
def approve_withdrawal_custom(
    request,
    withdraw_id,
):

    withdrawal = get_object_or_404(
        WithdrawalRequest,
        id=withdraw_id,
        status="PENDING",
    )

    result = process_withdrawal_approval(
        withdrawal
    )

    if (
        request.headers.get("x-requested-with")
        == "XMLHttpRequest"
    ):
        return JsonResponse(
            result,
            status=(
                200
                if result["status"] == "success"
                else 400
            ),
        )

    if result["status"] == "success":
        messages.success(
            request,
            result["message"],
        )
    else:
        messages.error(
            request,
            result["message"],
        )

    return redirect(
        "custom_withdrawal_dashboard"
    )


# ==========================================
# REJECT WITHDRAWAL
# ==========================================

@csrf_exempt
def reject_withdrawal_custom(
    request,
    withdraw_id,
):

    withdrawal = get_object_or_404(
        WithdrawalRequest,
        id=withdraw_id,
        status="PENDING",
    )

    withdrawal.status = "REJECTED"

    withdrawal.save(
        update_fields=["status"]
    )

    if (
        request.headers.get("x-requested-with")
        == "XMLHttpRequest"
    ):
        return JsonResponse({
            "status": "success",
            "message": (
                "Withdrawal request cancelled."
            ),
        })

    messages.warning(
        request,
        "Withdrawal request rejected.",
    )

    return redirect(
        "custom_withdrawal_dashboard"
    )