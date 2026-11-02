# myapp/models.py

from django.db import models, IntegrityError
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.cache import cache
import secrets
from .currency_utils import format_dollar, format_local_currency


# ==========================================================
# REGION CONSTANTS
# ==========================================================

COUNTRY_PK = "PK"
COUNTRY_IN = "IN"

COUNTRY_CHOICES = [
    (COUNTRY_PK, "Pakistan"),
    (COUNTRY_IN, "India"),
]

PK_ONLY_METHODS = frozenset({"JAZZCASHE", "EASYPAISA"})  # fixed typo guard
PK_ONLY_METHODS = frozenset({"JAZZCASH", "EASYPAISA"})
IN_ONLY_METHODS = frozenset({"RAZORPAY", "PHONEPE"})
ALL_REGION_METHODS = frozenset({"BINANCE", "USDT"})


class SystemSetting(models.Model):
    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.CharField(max_length=255, default="", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "System Setting"
        verbose_name_plural = "System Settings"

    def __str__(self):
        return f"Setting {self.key} = {self.value}"

    @classmethod
    def get_value(cls, key, default=""):
        cache_key = f"syssetting:{key}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            obj = cls.objects.get(key=key)
            val = obj.value
        except cls.DoesNotExist:
            val = default
        cache.set(cache_key, val, timeout=60)
        return val

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete(f"syssetting:{self.key}")

    def delete(self, *args, **kwargs):
        key = self.key
        super().delete(*args, **kwargs)
        cache.delete(f"syssetting:{key}")


class SystemConfiguration(models.Model):
    withdrawal_commission_percentage = models.PositiveIntegerField(default=5)
    platform_tax_percentage = models.PositiveIntegerField(default=15)
    winner_payout_percentage = models.PositiveIntegerField(default=85)

    usdt_wallet_address = models.CharField(max_length=255, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Global System Configuration"
        verbose_name_plural = "Global System Configuration"

    def clean(self):
        if self.platform_tax_percentage + self.winner_payout_percentage != 100:
            raise ValidationError(
                "The platform tax and winner payout percentages must equal exactly 100%."
            )
        if not 0 <= self.platform_tax_percentage <= 100:
            raise ValidationError("Platform tax must be between 0 and 100.")
        if not 0 <= self.winner_payout_percentage <= 100:
            raise ValidationError("Winner payout must be between 0 and 100.")
        if not 0 <= self.withdrawal_commission_percentage <= 100:
            raise ValidationError("Withdrawal commission must be between 0 and 100.")

    def save(self, *args, **kwargs):
        self.clean()
        self.pk = 1
        super().save(*args, **kwargs)

    # ==========================================================
    # ✅ P1-11 FIX: get_solo() race condition
    #
    # Pehle: get_or_create(pk=1) → concurrent requests me
    #        IntegrityError throw hota tha.
    #
    # Ab: explicit try/except + retry → race-safe.
    # ==========================================================

    @classmethod
    def get_solo(cls):
        try:
            return cls.objects.get(pk=1)
        except cls.DoesNotExist:
            pass

        try:
            return cls.objects.create(
                pk=1,
                defaults={
                    "withdrawal_commission_percentage": 5,
                    "platform_tax_percentage": 15,
                    "winner_payout_percentage": 85,
                },
            )
        except IntegrityError:
            # Another process created it between our get and create
            return cls.objects.get(pk=1)


class ExchangeRate(models.Model):
    COUNTRY_CHOICES = [
        ("PK", "Pakistan (PKR)"),
        ("IN", "India (INR)"),
    ]
    country = models.CharField(max_length=10, choices=COUNTRY_CHOICES, unique=True)
    usd_to_local_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1.00,
        help_text="1 USD = ? Local Currency",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_country_display()} - {self.usd_to_local_rate}"

    class Meta:
        verbose_name = "Exchange Rate"
        verbose_name_plural = "Exchange Rates (India & Pakistan)"


class UserProfileBalance(models.Model):
    nickname = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    profile_pic = models.ImageField(upload_to="profile_pics/", blank=True, null=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location_updated_at = models.DateTimeField(null=True, blank=True)
    device_fingerprint = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    device_token = models.CharField(max_length=255, unique=True, db_index=True)

    country = models.CharField(
        max_length=2,
        choices=COUNTRY_CHOICES,
        null=True,
        blank=True,
        db_index=True,
        help_text="Region locked after signup. PK or IN.",
    )

    currency = models.CharField(max_length=10, default="USD")
    coins = models.IntegerField(default=0)
    locked_coins = models.IntegerField(default=0)
    referral_code = models.CharField(max_length=6, unique=True, db_index=True, blank=True)

    last_free_spin = models.BigIntegerField(default=0)
    last_daily_bonus = models.BigIntegerField(default=0)

    has_withdrawal_pin = models.BooleanField(default=False)
    withdrawal_pin_hash = models.CharField(max_length=128, blank=True, null=True)

    withdrawal_pin_failed_attempts = models.PositiveIntegerField(default=0)
    withdrawal_pin_locked_until = models.BigIntegerField(default=0)

    has_made_first_deposit = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.referral_code:
            while True:
                code = secrets.token_hex(3).upper()
                if not UserProfileBalance.objects.filter(referral_code=code).exists():
                    self.referral_code = code
                    break
        super().save(*args, **kwargs)

    @property
    def coins_display(self):
        return format_dollar(self.coins)

    @property
    def local_balance_display(self):
        if self.currency == "USD":
            return format_dollar(self.coins)

        rate_obj = ExchangeRate.objects.filter(country=self.country).first()
        rate = rate_obj.usd_to_local_rate if rate_obj else 1.0

        from .currency_utils import convert_cents_to_local
        local = convert_cents_to_local(self.coins, rate)
        return format_local_currency(local, self.currency)


class ReferralSystem(models.Model):
    referrer = models.ForeignKey(
        UserProfileBalance, on_delete=models.CASCADE, related_name="referrals_initiated"
    )
    referred_user = models.ForeignKey(
        UserProfileBalance, on_delete=models.CASCADE, related_name="referred_by_link"
    )
    total_commission_earned = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    referrer_reward_paid = models.BooleanField(default=False)
    referrer_reward_amount = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("referred_user",)
        db_table = "referral_system"


class SystemTransactionLog(models.Model):
    LOG_TYPES = [
        ("DEPOSIT", "Manual Deposit Inflow"),
        ("WITHDRAWAL", "Manual Withdrawal Outflow"),
        ("WITHDRAWAL_REFUND", "Withdrawal Rejection Refund"),
        ("DEPOSIT_BONUS", "Deposit Welcome Bonus"),
        ("WAGER_ESCROW", "Match Entry Lock"),
        ("WAGER_PAYOUT", "Match Win Distribution"),
        ("WAGER_REFUND", "Match Entry Refund"),
        ("REFERRAL_BONUS", "Onboarding Sign-up Bonus"),
        ("REFERRAL_COMMISSION", "Dynamic Withdrawal Bonus Reward"),
        ("REFERRAL_INVITE_REWARD", "Referrer first-deposit reward"),
        ("SPIN_COST", "Lucky Spin Paid Cost"),
        ("SPIN_REWARD", "Lucky Spin Reward"),
        ("LEADERBOARD_REWARD", "Leaderboard Reward"),
        ("DAILY_BONUS", "Daily Login Bonus"),
    ]
    user_profile = models.ForeignKey(
        UserProfileBalance, on_delete=models.CASCADE, related_name="ledger_traces"
    )
    amount = models.IntegerField()
    log_type = models.CharField(max_length=30, choices=LOG_TYPES)
    reference_id = models.CharField(max_length=100, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class GameRoom(models.Model):
    STATUS_CHOICES = [
        ("LOBBY", "Lobby Waiting Frame"),
        ("ACTIVE", "Active Wagering Match"),
        ("COMPLETED", "Completed Ledger Payout"),
        ("CANCELLED", "Rollback Cancelled Fail-Safe"),
    ]
    game_id = models.CharField(max_length=100, unique=True, db_index=True)
    bet_amount = models.IntegerField(default=0)
    total_pool_escrow = models.IntegerField(default=0)
    service_fee_cut = models.IntegerField(default=0)
    winner_payout = models.IntegerField(default=0)
    game_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="LOBBY")
    is_private = models.BooleanField(default=False)
    room_code = models.CharField(max_length=10, unique=True, null=True, blank=True, db_index=True)
    max_players = models.PositiveIntegerField(default=2)
    host_token = models.CharField(max_length=255, blank=True, null=True)
    players = models.ManyToManyField(
        UserProfileBalance, related_name="active_wager_rooms", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.game_status == "ACTIVE" and (
            self.service_fee_cut + self.winner_payout != self.total_pool_escrow
        ):
            raise ValidationError(
                "Accounting Error: Combined platform fee and payout value "
                "mismatch total escrow pools."
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class GameHistory(models.Model):
    RESULT_CHOICES = [
        ("WON", "Won"),
        ("LOST", "Lost"),
        ("CANCELLED", "Cancelled"),
        ("SURRENDERED", "Surrendered"),
    ]
    MODE_CHOICES = [("2P", "Two Player"), ("4P", "Four Player")]

    user_profile = models.ForeignKey(
        UserProfileBalance, on_delete=models.CASCADE, related_name="game_history"
    )
    game_id = models.CharField(max_length=100, db_index=True)
    bet_amount = models.IntegerField(default=0)
    result = models.CharField(max_length=20, choices=RESULT_CHOICES)
    coins_change = models.IntegerField(default=0)
    game_mode = models.CharField(max_length=5, choices=MODE_CHOICES, default="2P")
    opponent_count = models.PositiveIntegerField(default=1)
    played_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-played_at"]


class SpinHistory(models.Model):
    user_profile = models.ForeignKey(
        UserProfileBalance, on_delete=models.CASCADE, related_name="spin_history"
    )
    gift_name = models.CharField(max_length=50)
    gift_emoji = models.CharField(max_length=10, default="🎁")
    coin_value = models.IntegerField(default=0)
    was_free = models.BooleanField(default=True)
    cost_paid = models.IntegerField(default=0)

    # ==========================================================
    # ✅ P1-1 FIX: Idempotency key
    #
    # Client UUID bhejta hai. Network retry / double-tap ho to
    # same UUID aata hai — backend duplicate detect karta hai
    # aur coins dobara deduct nahi hote.
    # ==========================================================
    client_request_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        help_text="Client-generated UUID for idempotency.",
    )
    won_index = models.IntegerField(default=0)  # stored for idempotent replay

    spun_at = models.DateTimeField(auto_now_add=True, db_index=True)


class LeaderboardReward(models.Model):
    PERIOD_CHOICES = [("weekly", "Weekly"), ("monthly", "Monthly")]
    period_type = models.CharField(max_length=10, choices=PERIOD_CHOICES)
    period_key = models.CharField(max_length=30, unique=True, db_index=True)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    distributed_at = models.DateTimeField(auto_now_add=True)
    distributed_by = models.CharField(max_length=100, blank=True)
    total_amount = models.IntegerField(default=0)
    winners_json = models.TextField(blank=True)


class LeaderboardRewardClaim(models.Model):
    PERIOD_CHOICES = [("weekly", "Weekly"), ("monthly", "Monthly")]
    user_profile = models.ForeignKey(
        UserProfileBalance, on_delete=models.CASCADE, related_name="leaderboard_claims"
    )
    amount = models.PositiveIntegerField()
    rank = models.PositiveIntegerField(default=0)
    period_type = models.CharField(max_length=10, choices=PERIOD_CHOICES)
    period_key = models.CharField(max_length=30, db_index=True)
    is_claimed = models.BooleanField(default=False, db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user_profile", "period_key")]


class SystemPaymentMethod(models.Model):
    METHOD_CHOICES = [
        ("JAZZCASH", "JazzCash"),
        ("EASYPAISA", "EasyPaisa"),
        ("BINANCE", "Binance"),
        ("USDT", "USDT"),
        ("RAZORPAY", "Razorpay"),
        ("PHONEPE", "PhonePe"),
    ]
    COUNTRY_SCOPE_CHOICES = [
        ("PK", "Pakistan"),
        ("IN", "India"),
        ("ALL", "All Regions"),
    ]
    method_type = models.CharField(max_length=20, choices=METHOD_CHOICES, unique=True)
    account_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    country = models.CharField(
        max_length=3,
        choices=COUNTRY_SCOPE_CHOICES,
        default="ALL",
        db_index=True,
        help_text="Which region can see this method.",
    )


class DepositRequest(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending Verification"),
        ("APPROVED", "Approved & Credited"),
        ("REJECTED", "Rejected / Invalid"),
    ]
    user_profile = models.ForeignKey(
        UserProfileBalance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deposit_requests",
    )
    device_token = models.CharField(max_length=255)
    amount = models.IntegerField()
    local_amount = models.FloatField(default=0.0)
    currency = models.CharField(max_length=10, default="USD")
    exchange_rate_used = models.FloatField(default=1.0)
    payment_method = models.CharField(max_length=50)
    sender_name = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def amount_display(self):
        return format_dollar(self.amount)

    @property
    def local_amount_display(self):
        return format_local_currency(self.local_amount, self.currency)


class WithdrawalRequest(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]
    METHOD_CHOICES = [
        ("JAZZCASH", "JazzCash"),
        ("EASYPAISA", "EasyPaisa"),
        ("BINANCE", "Binance"),
        ("USDT", "USDT"),
        ("RAZORPAY", "Razorpay"),
        ("PHONEPE", "PhonePe"),
    ]
    user_profile = models.ForeignKey(
        UserProfileBalance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawal_requests",
    )
    device_token = models.CharField(max_length=150, db_index=True)
    amount = models.PositiveIntegerField()
    local_amount = models.FloatField(default=0.0)
    currency = models.CharField(max_length=10, default="USD")
    exchange_rate_used = models.FloatField(default=1.0)

    client_request_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        help_text="Client-generated UUID for idempotency.",
    )

    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    account_title = models.CharField(max_length=100)
    account_number = models.CharField(max_length=100)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def amount_display(self):
        return format_dollar(self.amount)

    @property
    def local_amount_display(self):
        return format_local_currency(self.local_amount, self.currency)


class GameUser(models.Model):
    username = models.CharField(max_length=50, unique=True)
    email = models.EmailField(unique=True)
    device_id = models.CharField(max_length=255, db_index=True)
    device_fingerprint = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    auth_token = models.CharField(max_length=512, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    logged_out_at = models.DateTimeField(null=True, blank=True)


# ==========================================================
# ✅ P1-6 + P2-13 SUPPORT: Security Audit Log
#
# Har security-relevant event log hota hai:
#   - Failed PIN attempts (brute force detection)
#   - Device mismatch attempts (account takeover detection)
#   - Authz failures (privilege escalation detection)
#   - Rate limits (DoS detection)
#
# Used by admin to investigate incidents.
# ==========================================================

class SecurityAuditLog(models.Model):
    EVENT_CHOICES = [
        ("PIN_INCORRECT", "PIN Incorrect"),
        ("PIN_LOCKED", "PIN Locked"),
        ("PIN_RESET_REQUESTED", "PIN Reset Requested"),
        ("PIN_SET", "PIN Set"),
        ("PIN_CHANGED", "PIN Changed"),
        ("LOGIN_SUCCESS", "Login Success"),
        ("LOGIN_FAILED", "Login Failed"),
        ("LOGOUT", "Logout"),
        ("DEVICE_MISMATCH", "Device Mismatch"),
        ("AUTHZ_FAIL", "Authorization Fail"),
        ("RATE_LIMITED", "Rate Limited"),
        ("USERNAME_TAKEN", "Username Taken"),
        ("REFERRAL_SELF", "Self Referral Attempt"),
    ]

    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES, db_index=True)
    device_token = models.CharField(max_length=255, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Security Audit Log"
        verbose_name_plural = "Security Audit Logs"
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["device_token", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.event_type} | {self.device_token[:16]}"