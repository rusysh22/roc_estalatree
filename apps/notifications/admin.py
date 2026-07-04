from django.contrib import admin

from apps.notifications.models import EmailSuppression, NotificationLog


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
