from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
import secrets

class SystemConfiguration(models.Model):
    """Singleton pattern configuration controlling game economic variables globally."""
    withdrawal_commission_percentage = models.PositiveIntegerField(
        default=5, 
        help_text="Bonus cut percentage given to referrer upon an approved withdrawal."
    )
    platform_tax_percentage = models.PositiveIntegerField(
        default=15, 
        help_text="Wager pool platform tax percentage collected from match pools."
    )
    winner_payout_percentage = models.PositiveIntegerField(
        default=85, 
        help_text="Wager pool payout delivery payload percentage distributed to the winner."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Global System Configuration"
        verbose_name_plural = "Global System Configuration"

    def clean(self):
        if self.platform_tax_percentage + self.winner_payout_percentage != 100:
            raise ValidationError("The platform tax and winner payout percentages must equal exactly 100%.")

    def save(self, *args, **kwargs):
        self.clean()
        # Enforce Singleton pattern at database entry level
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                'withdrawal_commission_percentage': 5,
                'platform_tax_percentage': 15,
                'winner_payout_percentage': 85
            }
        )
        return obj

    def __str__(self):
        return f"System Matrix Rules [Tax: {self.platform_tax_percentage}% | Commission: {self.withdrawal_commission_percentage}%]"


class UserProfileBalance(models.Model):
    nickname = models.CharField(max_length=100, blank=True, null=True, help_text="User's custom display name.")
    phone_number = models.CharField(max_length=20, blank=True, null=True, unique=True, help_text="Verified mobile number.")

    """Player coin store keyed directly by hardware device tokens with unique referral codes."""
    device_token = models.CharField(max_length=255, unique=True, db_index=True)
    coins = models.IntegerField(default=0, help_text="Available active balance pool.")
    locked_coins = models.IntegerField(default=0, help_text="Escrowed coins held during active wagering matches.")
    referral_code = models.CharField(max_length=6, unique=True, db_index=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.referral_code:
            # Generate cryptographic secure uppercase alphanumeric codes without collision
            while True:
                code = secrets.token_hex(3).upper() # 6 characters alphanumeric
                if not UserProfileBalance.objects.filter(referral_code=code).exists():
                    self.referral_code = code
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        display_name = self.nickname if self.nickname else "Anonymous User"
        return f"{display_name} | {self.device_token} ({self.referral_code}) - Coins: {self.coins}"


class ReferralSystem(models.Model):
    """Immutable mapping tracking systemic invitation connections and accumulated bonuses."""
    referrer = models.ForeignKey(UserProfileBalance, on_delete=models.CASCADE, related_name="referrals_initiated")
    referred_user = models.OneToOneField(UserProfileBalance, on_delete=models.CASCADE, related_name="referred_by_link")
    total_commission_earned = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Referrer: {self.referrer.referral_code} ➡️ Used By: {self.referred_user.referral_code}"


class SystemTransactionLog(models.Model):
    """Explicit systemic auditing trace for compliance monitoring logs."""
    LOG_TYPES = [
        ('DEPOSIT', 'Manual Deposit Inflow'),
        ('WITHDRAWAL', 'Manual Withdrawal Outflow'),
        ('WAGER_ESCROW', 'Match Entry Lock'),
        ('WAGER_PAYOUT', 'Match Win Distribution'),
        ('REFERRAL_BONUS', 'Onboarding Sign-up Bonus'),
        ('REFERRAL_COMMISSION', 'Dynamic Withdrawal Bonus Reward'),
    ]
    user_profile = models.ForeignKey(UserProfileBalance, on_delete=models.CASCADE, related_name="ledger_traces")
    amount = models.IntegerField()
    log_type = models.CharField(max_length=25, choices=LOG_TYPES)
    reference_id = models.CharField(max_length=100, blank=True, null=True, help_text="Tracks match IDs or request tracking IDs.")
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.log_type}] {self.user_profile.device_token}: {self.amount}"


class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('LOBBY', 'Lobby Waiting Frame'),
        ('ACTIVE', 'Active Wagering Match'),
        ('COMPLETED', 'Completed Ledger Payout'),
        ('CANCELLED', 'Rollback Cancelled Fail-Safe'),
    ]

    game_id = models.CharField(max_length=100, unique=True, db_index=True)
    bet_amount = models.IntegerField(default=0, help_text="Wager fee requirement per individual player profile.")
    total_pool_escrow = models.IntegerField(default=0, help_text="Total pooled contribution values in escrow.")
    service_fee_cut = models.IntegerField(default=0, help_text="System administration platform tax calculated dynamically from setup configurations.")
    winner_payout = models.IntegerField(default=0, help_text="Delivery distribution payload sum calculated dynamically from setup configurations.")
    game_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='LOBBY')
    players = models.ManyToManyField(UserProfileBalance, related_name='active_wager_rooms', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        # Fail-safe check during validation loops to prevent coin leakage
        if self.game_status == 'ACTIVE' and (self.service_fee_cut + self.winner_payout != self.total_pool_escrow):
            raise ValidationError("Accounting Error: Combined platform fee and payout value mismatch total escrow pools.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Match {self.game_id} [{self.game_status}] Pool: {self.total_pool_escrow}"


class SystemPaymentMethod(models.Model):
    """PAGE 2: Admin setup configuration containing accounts details (JazzCash, etc.)"""
    METHOD_CHOICES = [
        ('JAZZCASH', 'JazzCash'),
        ('EASYPAISA', 'EasyPaisa'),
        ('BINANCE', 'Binance'),
    ]
    method_type = models.CharField(max_length=20, choices=METHOD_CHOICES, unique=True)
    account_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.get_method_type_display()} - {self.account_number}"


class DepositRequest(models.Model):
    """PAGE 1: Core payment verification log ledger waiting for manual oversight"""
    STATUS_CHOICES = [
        ('PENDING', 'Pending Verification'),
        ('APPROVED', 'Approved & Credited'),
        ('REJECTED', 'Rejected / Invalid'),
    ]
    device_token = models.CharField(max_length=255)
    amount = models.IntegerField()
    payment_method = models.CharField(max_length=50)
    sender_name = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.device_token} - {self.amount} ({self.status})"


class WithdrawalRequest(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    METHOD_CHOICES = [
        ('JAZZCASH', 'JazzCash'),
        ('EASYPAISA', 'EasyPaisa'),
        ('BINANCE', 'Binance'),
    ]

    device_token = models.CharField(max_length=150, db_index=True)
    amount = models.PositiveIntegerField()
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    account_title = models.CharField(max_length=100)
    account_number = models.CharField(max_length=100)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.method} Withdrawal ({self.amount} Coins) - {self.status}"