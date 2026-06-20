from django.contrib import admin
from django.utils import timezone

from apps.billing.models import (
    AffiliateCommission, AffiliateLink, Order, PaymentWebhook,
    SellerEarning, SellerPayout, Subscription, TopUp,
)


@admin.register(TopUp)
class TopUpAdmin(admin.ModelAdmin):
    list_display = ["public_id", "customer", "amount", "bonus", "status", "created_at"]
    list_filter = ["status", "gateway"]
    search_fields = ["public_id", "customer__user__email", "gateway_ref"]
    readonly_fields = ["public_id"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["public_id", "customer", "plan", "amount", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["public_id", "customer__user__email"]
    readonly_fields = ["public_id"]


@admin.register(PaymentWebhook)
class PaymentWebhookAdmin(admin.ModelAdmin):
    list_display = ["idempotency_key", "gateway", "processed_at", "created_at"]
    list_filter = ["gateway"]
    search_fields = ["idempotency_key"]
    readonly_fields = ["idempotency_key", "gateway", "payload", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["customer", "plan", "status", "current_period_end", "auto_renew"]
    list_filter = ["status", "auto_renew"]
    search_fields = ["customer__user__email", "plan__name"]


@admin.register(SellerEarning)
class SellerEarningAdmin(admin.ModelAdmin):
    list_display = ["pk", "seller", "order", "gross", "commission", "net", "status", "created_at"]
    list_filter = ["status", "seller"]
    search_fields = ["seller__name", "order__public_id"]
    readonly_fields = ["seller", "order", "gross", "commission", "net", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SellerPayout)
class SellerPayoutAdmin(admin.ModelAdmin):
    list_display = ["pk", "seller", "amount", "bank_name", "account_number", "status", "created_at"]
    list_filter = ["status", "seller"]
    search_fields = ["seller__name", "account_number", "account_name"]
    readonly_fields = ["seller", "amount", "bank_name", "account_number", "account_name", "created_at"]
    actions = ["approve_payouts", "complete_payouts", "reject_payouts"]

    def approve_payouts(self, request, queryset):
        queryset.filter(status=SellerPayout.Status.PENDING).update(status=SellerPayout.Status.APPROVED)
    approve_payouts.short_description = "Mark selected as Approved"

    def complete_payouts(self, request, queryset):
        queryset.filter(status=SellerPayout.Status.APPROVED).update(
            status=SellerPayout.Status.COMPLETED, processed_at=timezone.now()
        )
    complete_payouts.short_description = "Mark selected as Completed (paid out)"

    def reject_payouts(self, request, queryset):
        queryset.filter(status__in=[SellerPayout.Status.PENDING, SellerPayout.Status.APPROVED]).update(
            status=SellerPayout.Status.REJECTED
        )
    reject_payouts.short_description = "Mark selected as Rejected"


@admin.register(AffiliateLink)
class AffiliateLinkAdmin(admin.ModelAdmin):
    list_display = ["code", "seller", "affiliate_seller", "product", "commission_rate", "clicks", "is_active", "created_at"]
    list_filter = ["is_active", "seller"]
    search_fields = ["code", "seller__name", "label"]


@admin.register(AffiliateCommission)
class AffiliateCommissionAdmin(admin.ModelAdmin):
    list_display = ["pk", "link", "order", "amount", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["link__code", "order__public_id"]
    readonly_fields = ["link", "order", "amount", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False