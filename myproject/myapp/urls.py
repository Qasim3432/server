# myapp/urls.py

from django.urls import path

from .views.games import (
    initialize_game,
    join_wager_match,
)

from .views.game_rooms import (
    create_private_room,
    join_private_room,
    cancel_private_room,
    get_private_room_status,
)

from .views.auth import (
    verify_email_login,
    send_otp,
    logout_user,
    send_email_change_otp,
    check_username_availability,
)

from .views.pin_management import (
    get_pin_status,
    set_withdrawal_pin,
    change_withdrawal_pin,
    reset_pin_send_otp,
    reset_pin_verify_otp,
)

from .views.profile import update_user_profile

from .views.referrals import (
    verify_and_apply_referral,
    get_user_referral_code,
    get_referral_dashboard,
)

from .views.wallet import (
    get_active_payment_details,
    get_user_balance,
    get_transaction_history,
    update_user_location,
    get_app_config,   # ✅ wallet.py version — the live one
)

from .views.game_history import get_game_history

from .views.leaderboard import (
    get_leaderboard,
    get_my_pending_rewards,
    claim_leaderboard_reward,
)

from .views.gift import (
    get_spin_status,
    submit_spin,
    gift_config_api,
    gift_claim_api,
    get_spin_history,
    get_daily_bonus_status,
    claim_daily_bonus,
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
    get_withdrawal_status,
)

from .views.admin_gift import gift_control_dashboard

from .views.admin import (
    custom_admin_main_portal,
    custom_admin_settings,
    finance_management_dashboard,
    custom_exchange_rates_view,
)

from .views.admin_rewards import (
    leaderboard_rewards_dashboard,
    distribute_weekly_rewards,
    distribute_monthly_rewards,
)

from .views.admin_analytics import analytics_dashboard

from .views.agora_token import generate_agora_token


urlpatterns = [

    # =========================================================
    # GAME
    # =========================================================
    path("initialize-game/", initialize_game, name="initialize_game"),

    # =========================================================
    # AUTH
    # =========================================================
    path("api/auth/send-otp/", send_otp, name="send_otp"),
    path("api/auth/verify-email/", verify_email_login, name="verify_email_login"),
    path("api/auth/logout/", logout_user, name="logout_user"),
    path("api/auth/check-username/", check_username_availability, name="check_username_availability"),
    path("api/user/email-change-otp/", send_email_change_otp, name="email_change_otp"),

    # =========================================================
    # USER / PROFILE
    # =========================================================
    path("api/user/update-profile/", update_user_profile, name="update_user_profile"),

    # =========================================================
    # REFERRAL
    # =========================================================
    path("api/user/verify-referral/", verify_and_apply_referral, name="api_verify_referral"),
    path("api/user/referral/<str:device_token>/", get_user_referral_code, name="get_user_referral_code"),
    path("api/user/referral-dashboard/<str:device_token>/", get_referral_dashboard, name="get_referral_dashboard"),

    # =========================================================
    # PIN
    # =========================================================
    path("api/user/pin/status/", get_pin_status, name="pin_status"),
    path("api/user/pin/set/", set_withdrawal_pin, name="pin_set"),
    path("api/user/pin/change/", change_withdrawal_pin, name="pin_change"),
    path("api/user/pin/reset-request/", reset_pin_send_otp, name="pin_reset_request"),
    path("api/user/pin/reset-verify/", reset_pin_verify_otp, name="pin_reset_verify"),

    # =========================================================
    # WALLET
    # =========================================================
    path("api/deposit/methods/", get_active_payment_details, name="deposit_methods"),
    path("api/deposit/balance/<str:device_token>/", get_user_balance, name="user_balance"),
    path("api/deposit/submit/", submit_deposit_request, name="submit_deposit"),
    path("api/deposit/history/<str:device_token>/", get_transaction_history, name="get_transaction_history"),

    # =========================================================
    # WITHDRAW
    # =========================================================
    path("api/withdraw/submit/", submit_withdrawal_request, name="submit_withdrawal"),
    path("api/withdraw/status/<str:device_token>/", get_withdrawal_status, name="get_withdrawal_status"),

    # =========================================================
    # LOCATION
    # =========================================================
    path("api/user/location/", update_user_location, name="update_user_location"),

    # =========================================================
    # GAME HISTORY
    # =========================================================
    path("api/user/game-history/<str:device_token>/", get_game_history, name="get_game_history"),

    # =========================================================
    # LEADERBOARD
    # =========================================================
    path("api/leaderboard/", get_leaderboard, name="get_leaderboard"),
    path("api/leaderboard/pending-rewards/", get_my_pending_rewards, name="get_my_pending_rewards"),
    path("api/leaderboard/claim-reward/", claim_leaderboard_reward, name="claim_leaderboard_reward"),

    # =========================================================
    # DAILY BONUS
    # =========================================================
    path("api/user/daily-bonus/status/<str:device_token>/", get_daily_bonus_status, name="daily_bonus_status"),
    path("api/user/daily-bonus/claim/", claim_daily_bonus, name="daily_bonus_claim"),

    # =========================================================
    # APP CONFIG
    # =========================================================
    path("api/config/app/", get_app_config, name="app_config"),

    # =========================================================
    # GIFT
    # =========================================================
    path("api/gift/status/", get_spin_status, name="gift_status"),
    path("api/gift/spin/", submit_spin, name="gift_spin"),
    path("api/gift/config/", gift_config_api, name="gift_config"),
    path("api/gift/claim/", gift_claim_api, name="gift_claim"),
    path("api/user/spin-history/<str:device_token>/", get_spin_history, name="get_spin_history"),

    # =========================================================
    # AGORA VOICE
    # =========================================================
    path("api/agora/token/", generate_agora_token, name="agora_token"),

    # =========================================================
    # WAGER
    # =========================================================
    path("api/wager/join/", join_wager_match, name="join_wager_match"),

    # =========================================================
    # PRIVATE ROOMS
    # =========================================================
    path("api/game/create-room/", create_private_room, name="create_private_room"),
    path("api/game/join-room/", join_private_room, name="join_private_room"),
    path("api/game/cancel-room/", cancel_private_room, name="cancel_private_room"),
    path("api/game/room-status/<str:game_id>/", get_private_room_status, name="get_private_room_status"),

    # =========================================================
    # ADMIN CUSTOM PORTAL & DASHBOARDS
    # =========================================================
    path("management/", custom_admin_main_portal, name="custom_admin_main_portal"),
    path("management/exchange-rates/", custom_exchange_rates_view, name="custom_exchange_rates"),
    path("management/dashboard/deposits/", custom_deposit_dashboard, name="custom_deposit_dashboard"),
    path("management/dashboard/deposits/approve/<int:deposit_id>/", approve_deposit_custom, name="approve_deposit_custom"),
    path("management/dashboard/deposits/reject/<int:deposit_id>/", reject_deposit_custom, name="reject_deposit_custom"),
    path("management/dashboard/withdrawals/", custom_withdrawal_dashboard, name="custom_withdrawal_dashboard"),
    path("management/dashboard/withdrawals/approve/<int:withdraw_id>/", approve_withdrawal_custom, name="approve_withdrawal_custom"),
    path("management/dashboard/withdrawals/reject/<int:withdraw_id>/", reject_withdrawal_custom, name="reject_withdrawal_custom"),
    path("management/dashboard/gift/", gift_control_dashboard, name="gift_control_dashboard"),
    path("management/settings/", custom_admin_settings, name="custom_admin_settings"),
    path("dashboard/finance/", finance_management_dashboard, name="finance_management_dashboard"),
    path("management/dashboard/rewards/", leaderboard_rewards_dashboard, name="leaderboard_rewards_dashboard"),
    path("management/dashboard/rewards/distribute-weekly/", distribute_weekly_rewards, name="distribute_weekly_rewards"),
    path("management/dashboard/rewards/distribute-monthly/", distribute_monthly_rewards, name="distribute_monthly_rewards"),
    path("management/dashboard/analytics/", analytics_dashboard, name="analytics_dashboard"),
]