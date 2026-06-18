from django.contrib import admin

from apps.billing.models import Order, PaymentWebhook, Subscription, TopUp


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