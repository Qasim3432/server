from django.http import JsonResponse

from ..models import (
    DepositRequest,
    WithdrawalRequest,
    SystemPaymentMethod,
    UserProfileBalance,
)


def get_transaction_history(request, device_token):
    """
    Return combined deposit and withdrawal history.
    """

    transactions = []

    deposits = (
        DepositRequest.objects
        .filter(device_token=device_token)
        .order_by("-created_at")
    )

    for deposit in deposits:
        transactions.append({
            "type": "DEPOSIT",
            "amount": deposit.amount,
            "status": deposit.status,
            "date": deposit.created_at,
        })

    withdrawals = (
        WithdrawalRequest.objects
        .filter(device_token=device_token)
        .order_by("-created_at")
    )

    for withdrawal in withdrawals:
        transactions.append({
            "type": "WITHDRAWAL",
            "amount": withdrawal.amount,
            "status": withdrawal.status,
            "date": withdrawal.created_at,
        })

    # Sort using actual datetime instead of
    # formatted date strings.
    transactions.sort(
        key=lambda item: item["date"],
        reverse=True,
    )

    for item in transactions:
        item["date"] = item["date"].strftime(
            "%d %b %Y, %I:%M %p"
        )

    return JsonResponse({
        "status": "success",
        "transactions": transactions,
    })


def get_active_payment_details(request):

    methods = (
        SystemPaymentMethod.objects
        .filter(is_active=True)
    )

    data = {
        method.method_type: {
            "name": method.account_name,
            "number": method.account_number,
        }
        for method in methods
    }

    return JsonResponse({
        "status": "success",
        "methods": data,
    })


def get_user_balance(request, device_token):

    profile, _ = (
        UserProfileBalance.objects
        .get_or_create(
            device_token=device_token
        )
    )

    return JsonResponse({
        "status": "success",
        "coins": profile.coins,
    })