import json

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.csrf import csrf_exempt

from ..models import (
    DepositRequest,
    UserProfileBalance,
    SystemTransactionLog,
)


# ==========================================
# MOBILE DEPOSIT
# ==========================================

@csrf_exempt
def submit_deposit_request(request):

    if request.method != "POST":
        return JsonResponse(
            {"error": "POST required"},
            status=405,
        )

    try:
        data = json.loads(request.body)

        device_token = data.get("device_token")
        amount = int(data.get("amount", 0))
        method = data.get("payment_method")
        sender_name = data.get(
            "sender_name",
            "",
        )

        if (
            not device_token
            or amount <= 0
            or not method
        ):
            return JsonResponse(
                {
                    "error": (
                        "Invalid payload values "
                        "validation failure"
                    )
                },
                status=400,
            )

        DepositRequest.objects.create(
            device_token=device_token,
            amount=amount,
            payment_method=method,
            sender_name=sender_name,
            status="PENDING",
        )

        return JsonResponse({
            "status": "success",
            "message": (
                "Verification submitted successfully!"
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
# ADMIN DEPOSIT DASHBOARD
# ==========================================

def custom_deposit_dashboard(request):

    deposits = (
        DepositRequest.objects
        .all()
        .order_by("-created_at")
    )

    context = {
        "deposit_items": deposits
    }

    if (
        request.method == "GET"
        and request.headers.get(
            "x-requested-with"
        ) == "XMLHttpRequest"
    ):
        return render(
            request,
            "deposit_table_partial.html",
            context,
        )

    return render(
        request,
        "deposit_change_form.html",
        context,
    )


# ==========================================
# APPROVE DEPOSIT
# ==========================================

@csrf_exempt
def approve_deposit_custom(
    request,
    deposit_id,
):

    with transaction.atomic():

        deposit = get_object_or_404(
            DepositRequest,
            id=deposit_id,
            status="PENDING",
        )

        profile, _ = (
            UserProfileBalance.objects
            .select_for_update()
            .get_or_create(
                device_token=deposit.device_token
            )
        )

        profile.coins += deposit.amount

        profile.save(
            update_fields=["coins"]
        )

        deposit.status = "APPROVED"

        deposit.save(
            update_fields=["status"]
        )

        SystemTransactionLog.objects.create(
            user_profile=profile,
            amount=deposit.amount,
            log_type="DEPOSIT",
            reference_id=str(deposit.id),
        )

    if (
        request.headers.get("x-requested-with")
        == "XMLHttpRequest"
    ):
        return JsonResponse({
            "status": "success",
            "message": (
                f"Approved {deposit.amount} "
                "coins successfully!"
            ),
        })

    messages.success(
        request,
        (
            f"Approved {deposit.amount} coins "
            f"for {deposit.device_token} successfully!"
        ),
    )

    return redirect(
        "custom_deposit_dashboard"
    )


# ==========================================
# REJECT DEPOSIT
# ==========================================

@csrf_exempt
def reject_deposit_custom(
    request,
    deposit_id,
):

    deposit = get_object_or_404(
        DepositRequest,
        id=deposit_id,
        status="PENDING",
    )

    deposit.status = "REJECTED"

    deposit.save(
        update_fields=["status"]
    )

    if (
        request.headers.get("x-requested-with")
        == "XMLHttpRequest"
    ):
        return JsonResponse({
            "status": "success",
            "message": "Deposit request rejected.",
        })

    messages.error(
        request,
        (
            f"Rejected deposit request from "
            f"{deposit.device_token}."
        ),
    )

    return redirect(
        "custom_deposit_dashboard"
    )