from django.urls import path

from .views.games import (
    initialize_game,
    join_wager_match,
    finalize_game_wager,
    cancel_game_wager,
)

from .views.profile import (
    update_user_profile,
)

from .views.referrals import (
    verify_and_apply_referral,
    get_user_referral_code,
)

from .views.wallet import (
    get_active_payment_details,
    get_user_balance,
    get_transaction_history,
)

from .views.deposits import (
    submit_deposit_request,
    custom_deposit_dashboard,
    approve_deposit_custom,
    reject_deposit_custom,
)

from .views.withdrawals import (
    submit_withdrawal_request,
    custom_withdrawal_dashboard,
    approve_withdrawal_custom,
    reject_withdrawal_custom,
)

from .views.admin import (
    custom_admin_main_portal,
    custom_admin_settings,
    finance_management_dashboard,
)

from .views.auth import (
    create_test_user,
)

urlpatterns = [

    # ==========================================================
    # 🎮 GAME INITIALIZATION
    # ==========================================================

    path(
        "initialize-game/",
        initialize_game,
        name="initialize_game",
    ),

    # ==========================================================
    # 📱 CLIENT ENDPOINTS — MOBILE APP
    # ==========================================================

    # --------------------------
    # USER PROFILE
    # --------------------------

    path(
        "api/test/create-user/",
        create_test_user,
        name="create_test_user",
    ),

    path(  # YE NAYA ADD KIYA HAI
        "api/register/",
        create_test_user,
        name="api_register",
    ),

    path(
        "api/user/update-profile/",
        update_user_profile,
        name="update_user_profile",
    ),

    # --------------------------
    # REFERRALS
    # --------------------------

    path(
        "api/user/verify-referral/",
        verify_and_apply_referral,
        name="api_verify_referral",
    ),

    path(
        "api/user/referral/<str:device_token>/",
        get_user_referral_code,
        name="get_user_referral_code",
    ),

    # --------------------------
    # DEPOSIT / WALLET
    # --------------------------

    path(
        "api/deposit/methods/",
        get_active_payment_details,
        name="deposit_methods",
    ),

    path(
        "api/deposit/balance/<str:device_token>/",
        get_user_balance,
        name="user_balance",
    ),

    path(
        "api/deposit/submit/",
        submit_deposit_request,
        name="submit_deposit",
    ),

    path(
        "api/deposit/history/<str:device_token>/",
        get_transaction_history,
        name="get_transaction_history",
    ),

    # --------------------------
    # WITHDRAWAL
    # --------------------------

    path(
        "api/withdraw/submit/",
        submit_withdrawal_request,
        name="submit_withdrawal",
    ),

    # --------------------------
    # WAGER / GAME
    # --------------------------

    path(
        "api/wager/join/",
        join_wager_match,
        name="join_wager_match",
    ),

    path(
        "api/wager/finalize/",
        finalize_game_wager,
        name="finalize_game_wager",
    ),

    path(
        "api/wager/cancel/",
        cancel_game_wager,
        name="cancel_game_wager",
    ),

    # ==========================================================
    # 🛡️ CUSTOM MANAGEMENT ADMIN PORTAL
    # ==========================================================

    # --------------------------
    # MAIN MANAGEMENT HUB
    # --------------------------

    path(
        "management/",
        custom_admin_main_portal,
        name="custom_admin_main_portal",
    ),

    # --------------------------
    # DEPOSIT DASHBOARD
    # --------------------------

    path(
        "management/dashboard/deposits/",
        custom_deposit_dashboard,
        name="custom_deposit_dashboard",
    ),

    path(
        "management/dashboard/deposits/approve/<int:deposit_id>/",
        approve_deposit_custom,
        name="approve_deposit_custom",
    ),

    path(
        "management/dashboard/deposits/reject/<int:deposit_id>/",
        reject_deposit_custom,
        name="reject_deposit_custom",
    ),

    # --------------------------
    # WITHDRAWAL DASHBOARD
    # --------------------------

    path(
        "management/dashboard/withdrawals/",
        custom_withdrawal_dashboard,
        name="custom_withdrawal_dashboard",
    ),

    path(
        "management/dashboard/withdrawals/approve/<int:withdraw_id>/",
        approve_withdrawal_custom,
        name="approve_withdrawal_custom",
    ),

    path(
        "management/dashboard/withdrawals/reject/<int:withdraw_id>/",
        reject_withdrawal_custom,
        name="reject_withdrawal_custom",
    ),

    # --------------------------
    # PAYMENT SETTINGS
    # --------------------------

    path(
        "management/settings/",
        custom_admin_settings,
        name="custom_admin_settings",
    ),

    # --------------------------
    # FINANCE DASHBOARD
    # --------------------------

    path(
        "dashboard/finance/",
        finance_management_dashboard,
        name="finance_management_dashboard",
    ),
]