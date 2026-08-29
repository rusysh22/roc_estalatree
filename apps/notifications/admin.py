from django.contrib import admin

from apps.notifications.models import (
    EmailSuppression,
    NotificationDelivery,
    NotificationLog,
    WhatsAppOTP,
    WhatsAppSuppression,
)


@admin.register(EmailSuppression)
class EmailSuppressionAdmin(admin.ModelAdmin):
    list_display = ("email", "reason", "created_at")
    list_filter = ("reason",)
    search_fields = ("email", "detail")


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("recipient", "channel", "dedup_key", "created_at")
    list_filter = ("channel",)
    search_fields = ("recipient", "dedup_key")


@admin.register(WhatsAppSuppression)
class WhatsAppSuppressionAdmin(admin.ModelAdmin):
    list_display = ("number", "reason", "created_at")
    list_filter = ("reason",)
    search_fields = ("number", "detail")


@admin.register(WhatsAppOTP)
class WhatsAppOTPAdmin(admin.ModelAdmin):
    list_display = ("number", "customer", "attempts", "expires_at", "consumed_at", "created_at")
    search_fields = ("number", "customer__user__email")
    readonly_fields = ("customer", "number", "code_hash", "expires_at", "attempts", "consumed_at")


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ("recipient", "channel", "event", "status", "provider", "created_at")
    list_filter = ("channel", "status", "provider")
    search_fields = ("recipient", "event", "provider_msg_id")
    readonly_fields = tuple(
        f.name for f in NotificationDelivery._meta.fields
    )
