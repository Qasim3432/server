from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from .models import SystemPaymentMethod, DepositRequest, UserProfileBalance, WithdrawalRequest

# ==============================================================================
# PAGE 1: TRANSACTION VERIFICATION BOARD
# ==============================================================================
@admin.register(DepositRequest)
class DepositRequestAdmin(admin.ModelAdmin):
    """
    This is your manual review dashboard. It pulls incoming requests from the app.
    You use the checkboxes and the 'Actions' dropdown to approve coins.
    """
    # Columns that show up in the main list view table
    list_display = ('device_token', 'amount', 'payment_method', 'sender_name', 'status', 'created_at')
    
    # Sidebar filters to quickly see what is 'PENDING'
    list_filter = ('status', 'payment_method')
    
    # Search bar to find specific users or transactions
    search_fields = ('device_token', 'sender_name')
    
    # Custom bulk actions dropdown utilities
    actions = ['approve_deposits', 'reject_deposits']

    def approve_deposits(self, request, queryset):
        """Action trigger that automatically updates balances upon admin approval"""
        count = 0
        for deposit in queryset.filter(status='PENDING'):
            # Fetch the user profile balance mapping using their device token string
            profile, _ = UserProfileBalance.objects.get_or_create(device_token=deposit.device_token)
            
            # Credit the exact coin value requested
            profile.coins += deposit.amount
            profile.save()
            
            # Mark transaction record clear
            deposit.status = 'APPROVED'
            deposit.save()
            count += 1
            
        self.message_user(request, f"Successfully approved {count} deposit receipts and updated player balances!")
    
    def reject_deposits(self, request, queryset):
        """Action trigger to deny invalid requests"""
        updated = queryset.filter(status='PENDING').update(status='REJECTED')
        self.message_user(request, f"Marked {updated} pending deposits as rejected.")

    # Custom text labels inside the action dropdown menu selection bar
    approve_deposits.short_description = "✅ Approve selected deposit receipts"
    reject_deposits.short_description = "❌ Reject selected deposit receipts"


# ==============================================================================
# PAGE 2: ACCOUNT NUMBERS CONFIGURATION
# ==============================================================================
@admin.register(SystemPaymentMethod)
class SystemPaymentMethodAdmin(admin.ModelAdmin):
    """
    This is where you add or modify your account numbers (JazzCash, EasyPaisa, etc.).
    Whatever you save here updates instantly inside the Android app layout.
    """
    list_display = ('method_type', 'account_name', 'account_number', 'is_active')
    list_editable = ('account_name', 'account_number', 'is_active')


# Optional: Add user profile visibility to manually edit player coins if needed
@admin.register(UserProfileBalance)
class UserProfileBalanceAdmin(admin.ModelAdmin):
    list_display = ('device_token', 'coins')
    search_fields = ('device_token',)



@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ('device_token', 'amount', 'method', 'account_title', 'account_number', 'status', 'created_at')
    list_filter = ('status', 'method')
    readonly_fields = ('status', 'created_at', 'updated_at') # Kept status read-only so they must use the template panel buttons

    # 🟢 INJECT URLS INTO ADMIN INSTANCE
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:object_id>/actions/approve/', self.admin_site.admin_view(self.approve_request), name='withdraw-approve'),
            path('<int:object_id>/actions/reject/', self.admin_site.admin_view(self.reject_request), name='withdraw-reject'),
        ]
        return custom_urls + urls

    # 🟢 APPROVE LOGIC PIPELINE
    def approve_request(self, request, object_id):
        obj = WithdrawalRequest.objects.get(pk=object_id)
        if obj.status == 'PENDING':
            profile, _ = UserProfileBalance.objects.get_or_create(device_token=obj.device_token)
            if profile.coins >= obj.amount:
                profile.coins -= obj.amount
                profile.save()
                
                obj.status = 'APPROVED'
                obj.save()
                self.message_user(request, "Withdrawal approved successfully!", messages.SUCCESS)
            else:
                self.message_user(request, "Error: User does not have sufficient balance!", messages.ERROR)
        return redirect(f'../../')

    # 🟢 REJECT LOGIC PIPELINE
    def reject_request(self, request, object_id):
        obj = WithdrawalRequest.objects.get(pk=object_id)
        if obj.status == 'PENDING':
            obj.status = 'REJECTED'
            obj.save()
            self.message_user(request, "Withdrawal request rejected.", messages.WARNING)
        return redirect(f'../../')