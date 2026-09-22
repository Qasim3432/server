from django.urls import path

from .views.games import (
    initialize_game,
    join_wager_match,
    finalize_game_wager,
    cancel_game_wager,
)

from .views.auth import (
    verify_email_login,
    send_otp,
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

from .views.gift import (
    get_spin_status,
    submit_spin,
    gift_config_api,
    gift_claim_api,
)

from .views.admin_gift import (
    gift_control_dashboard,
)

from .views.admin import (
    custom_admin_main_portal,
    custom_admin_settings,
    finance_management_dashboard,
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

    path(
        "api/user/update-profile/",
        update_user_profile,
        name="update_user_profile",
    ),

    path(
        "api/auth/verify-email/",
        verify_email_login,
        name="verify_email_login",
    ),

    path(
        "api/auth/send-otp/",
        send_otp,
        name="send_otp",
    ),

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

    path(
        "api/withdraw/submit/",
        submit_withdrawal_request,
        name="submit_withdrawal",
    ),

    # --------------------------
    # GIFT / LUCKY SPIN
    # --------------------------

    path(
        "api/gift/status/",
        get_spin_status,
        name="gift_status",
    ),

    path(
        "api/gift/spin/",
        submit_spin,
        name="gift_spin",
    ),

    path(
        "api/gift/config/",
        gift_config_api,
        name="gift_config",
    ),

    path(
        "api/gift/claim/",
        gift_claim_api,
        name="gift_claim",
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

    path(
        "management/",
        custom_admin_main_portal,
        name="custom_admin_main_portal",
    ),

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

    path(
        "management/dashboard/gift/",
        gift_control_dashboard,
        name="gift_control_dashboard",
    ),

    path(
        "management/settings/",
        custom_admin_settings,
        name="custom_admin_settings",
    ),

    path(
        "dashboard/finance/",
        finance_management_dashboard,
        name="finance_management_dashboard",
    ),
]