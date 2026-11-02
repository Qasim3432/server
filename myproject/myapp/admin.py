from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from django.db import transaction
from django.utils.html import format_html

from .models import (
    SystemPaymentMethod,
    DepositRequest,
    UserProfileBalance,
    WithdrawalRequest,
    SystemSetting,
    ReferralSystem,
    SystemTransactionLog,
    # SystemConfiguration,  <-- ❌ REMOVED (Ab ye default admin me nahi dikhega)
)

from .currency_utils import format_dollar  # ✅ Import kiya
from .services.wager_service import process_withdrawal_approval  # ✅ NEW — approve flow


# ==============================================================================
# PAGE 1: TRANSACTION VERIFICATION BOARD
# ==============================================================================

@admin.register(DepositRequest)
class DepositRequestAdmin(admin.ModelAdmin):

    list_display = (
        'device_token',
        'amount_display', # ✅ Formatted to $
        'payment_method',
        'sender_name',
        'status',
        'created_at'
    )

    list_filter = (
        'status',
        'payment_method'
    )

    search_fields = (
        'device_token',
        'sender_name'
    )

    actions = [
        'approve_deposits',
        'reject_deposits'
    ]

    @admin.display(description="Amount")
    def amount_display(self, obj):
        return format_dollar(obj.amount)

    def approve_deposits(self, request, queryset):

        count = 0
        total_referrer_rewards = 0

        for deposit in queryset.filter(status='PENDING'):

            with transaction.atomic():

                profile, _ = (
                    UserProfileBalance.objects
                    .select_for_update()
                    .get_or_create(
                        device_token=deposit.device_token
                    )
                )

                is_first = (
                    not profile.has_made_first_deposit
                )

                profile.coins += deposit.amount

                if is_first:
                    profile.has_made_first_deposit = True

                profile.save(
                    update_fields=[
                        "coins",
                        "has_made_first_deposit",
                    ]
                )

                SystemTransactionLog.objects.create(
                    user_profile=profile,
                    amount=deposit.amount,
                    log_type="DEPOSIT",
                    reference_id=f"DEP_{deposit.id}",
                )

                deposit.status = 'APPROVED'
                deposit.save(update_fields=['status'])

                if is_first:

                    total_referrer_rewards += (
                        self._pay_referrer_reward(
                            profile,
                            deposit.id,
                        )
                    )

                count += 1

        msg = (
            f"Successfully approved {count} "
            f"deposit receipts and updated "
            f"player balances!"
        )

        if total_referrer_rewards > 0:
            msg += (
                f" Referrer rewards paid: "
                f"{format_dollar(total_referrer_rewards)}."
            )

        self.message_user(request, msg)

    def _pay_referrer_reward(self, referred_profile, deposit_id):

        referral = (
            ReferralSystem.objects
            .select_for_update()
            .select_related('referrer')
            .filter(
                referred_user=referred_profile,
                referrer_reward_paid=False,
            )
            .first()
        )

        if not referral:
            return 0

        if not referral.referrer:
            return 0

        reward = int(referral.referrer_reward_amount or 50)

        if reward <= 0:
            return 0

        referrer = (
            UserProfileBalance.objects
            .select_for_update()
            .filter(id=referral.referrer.id)
            .first()
        )

        if not referrer:
            return 0

        referrer.coins += reward
        referrer.save(update_fields=["coins"])

        referral.referrer_reward_paid = True
        referral.total_commission_earned = (
            referral.total_commission_earned + reward
        )
        referral.save(
            update_fields=[
                "referrer_reward_paid",
                "total_commission_earned",
            ]
        )

        SystemTransactionLog.objects.create(
            user_profile=referrer,
            amount=reward,
            log_type="REFERRAL_INVITE_REWARD",
            reference_id=(
                f"FIRST_DEP_{referred_profile.id}"
                f"_DEP_{deposit_id}"
            ),
        )

        print(
            f"💰 REFERRER REWARD PAID (admin) | "
            f"referrer={referrer.device_token} | "
            f"amount={format_dollar(reward)}"
        )

        return reward

    def reject_deposits(self, request, queryset):

        updated = (
            queryset.filter(status='PENDING')
            .update(status='REJECTED')
        )

        self.message_user(
            request,
            f"Marked {updated} pending deposits as rejected."
        )

    approve_deposits.short_description = "✅ Approve selected deposit receipts"
    reject_deposits.short_description = "❌ Reject selected deposit receipts"


# ==============================================================================
# PAGE 2: PAYMENT METHOD CONFIGURATION (region-aware)
# ==============================================================================

@admin.register(SystemPaymentMethod)
class SystemPaymentMethodAdmin(admin.ModelAdmin):

    list_display = (
        'method_type',
        'country',
        'account_name',
        'account_number',
        'is_active',
    )

    list_filter = (
        'country',
        'is_active',
    )

    list_editable = (
        'country',
        'account_name',
        'account_number',
        'is_active',
    )

    help_text = (
        "Country: PK = only Pakistan, IN = only India, ALL = both regions. "
        "BINANCE and USDT should be ALL. JAZZCASH/EASYPAISA = PK. "
        "RAZORPAY/PHONEPE = IN."
    )


# ==============================================================================
# USER PROFILE BALANCE — country visible
# ==============================================================================

@admin.register(UserProfileBalance)
class UserProfileBalanceAdmin(admin.ModelAdmin):

    list_display = (
        'device_token',
        'nickname',
        'country',
        'ip_address',
        'location_link',
        'coins_display',        # ✅ Formatted to $
        'locked_coins_display', # ✅ Formatted to $
        'created_at',
    )

    list_filter = (
        'country',
        'created_at',
    )

    search_fields = (
        'device_token',
        'nickname',
        'email',
        'ip_address',
    )

    readonly_fields = (
        'country',
        'ip_address',
        'location_link',
        'location_updated_at',
        'created_at',
        'updated_at',
    )

    ordering = (
        '-created_at',
    )

    @admin.display(description="Coins Balance")
    def coins_display(self, obj):
        return format_dollar(obj.coins)

    @admin.display(description="Locked Coins")
    def locked_coins_display(self, obj):
        return format_dollar(obj.locked_coins)

    def location_link(self, obj):

        if obj.latitude is None or obj.longitude is None:
            return "—"

        url = (
            f"https://www.google.com/maps"
            f"?q={obj.latitude},{obj.longitude}"
        )

        return format_html(
            '<a href="{}" target="_blank">📍 Map</a>',
            url
        )

    location_link.short_description = "Location"


# ==============================================================================
# WITHDRAWAL REQUESTS
# ==============================================================================

@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):

    list_display = (
        'device_token',
        'amount_display', # ✅ Formatted to $
        'method',
        'account_title',
        'account_number',
        'status',
        'created_at'
    )

    list_filter = (
        'status',
        'method'
    )

    readonly_fields = (
        'status',
        'created_at',
        'updated_at'
    )

    @admin.display(description="Amount")
    def amount_display(self, obj):
        return format_dollar(obj.amount)

    def get_urls(self):

        urls = super().get_urls()

        custom_urls = [
            path(
                '<int:object_id>/actions/approve/',
                self.admin_site.admin_view(self.approve_request),
                name='withdraw-approve'
            ),
            path(
                '<int:object_id>/actions/reject/',
                self.admin_site.admin_view(self.reject_request),
                name='withdraw-reject'
            ),
        ]

        return custom_urls + urls

    # ==========================================================
    # ✅ FIX: approve_request
    #
    # Pehle yahan sirf status='APPROVED' set hota tha, jisse referrer
    # ko commission nahi milti thi — Django admin aur custom dashboard
    # ka behavior different tha.
    #
    # Ab custom dashboard wala hi `process_withdrawal_approval` call
    # karte hain taake referral commission bhi trigger ho.
    # ==========================================================

    def approve_request(self, request, object_id):

        result = process_withdrawal_approval(int(object_id))

        if result["status"] == "success":
            self.message_user(
                request,
                result["message"],
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                result["message"],
                messages.ERROR,
            )

        return redirect(f'../../')

    # ==========================================================
    # ✅ FIX: reject_request
    #
    # Pehle log_type="WAGER_REFUND" tha (galat). Ab
    # log_type="WITHDRAWAL_REFUND" (sahi). Saath me safer lookup.
    # ==========================================================

    def reject_request(self, request, object_id):

        with transaction.atomic():

            obj = (
                WithdrawalRequest.objects
                .select_for_update()
                .filter(pk=object_id, status='PENDING')
                .first()
            )

            if not obj:
                self.message_user(
                    request,
                    "Already processed.",
                    messages.WARNING,
                )
                return redirect(f'../../')

            profile = (
                UserProfileBalance.objects
                .select_for_update()
                .filter(device_token=obj.device_token)
                .first()
            )

            if profile:

                profile.coins += obj.amount
                profile.save(update_fields=['coins'])

                SystemTransactionLog.objects.create(
                    user_profile=profile,
                    amount=obj.amount,
                    log_type="WITHDRAWAL_REFUND",  # ✅ FIX
                    reference_id=f"WD_REJECT_{obj.id}",
                )

            obj.status = 'REJECTED'
            obj.save(update_fields=['status'])

            self.message_user(
                request,
                (
                    f"Withdrawal rejected. "
                    f"{format_dollar(obj.amount)} refunded."
                ),
                messages.WARNING,
            )

        return redirect(f'../../')


# ==============================================================================
# SYSTEM SETTINGS
# ==============================================================================

@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):

    list_display = (
        'key',
        'value',
        'updated_at',
    )

    search_fields = (
        'key',
        'value',
    )

    list_editable = (
        'value',
    )

    ordering = (
        'key',
    )

    help_text = (
        "Common keys: support_whatsapp, support_telegram, "
        "support_email, terms_text, privacy_text, app_version, "
        "gift_enabled, paid_spin_cost, referral_share_text"
    )