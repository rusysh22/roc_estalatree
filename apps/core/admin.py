"""Core admin — AuditLog and Setting. AuditLog is read-only."""
from django.contrib import admin

from apps.core.models import AuditLog, Setting


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "action", "target_type", "target_id"]
    list_filter = ["action", "target_type"]
    search_fields = ["actor__email", "action", "target_id"]
    readonly_fields = ["actor", "action", "target_type", "target_id", "meta", "created_at"]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ["key", "value", "updated_at"]
    search_fields = ["key"]
