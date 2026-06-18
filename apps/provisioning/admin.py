from django.contrib import admin

from apps.provisioning.models import Deliverable, Entitlement, Grant, Secret


class DeliverableInline(admin.TabularInline):
    model = Deliverable
    extra = 0
    fields = ["type", "config"]


@admin.register(Deliverable)
class DeliverableAdmin(admin.ModelAdmin):
    list_display = ["plan", "type", "created_at"]
    list_filter = ["type"]
    search_fields = ["plan__name"]


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "value"]
    search_fields = ["key", "name"]
    filter_horizontal = ["plans"]


@admin.register(Grant)
class GrantAdmin(admin.ModelAdmin):
    list_display = ["customer", "type", "status", "valid_until", "created_at"]
    list_filter = ["type", "status"]
    search_fields = ["customer__user__email"]
    readonly_fields = ["type"]


@admin.register(Secret)
class SecretAdmin(admin.ModelAdmin):
    list_display = ["grant", "is_revealed", "rotated_at", "created_at"]
    readonly_fields = ["grant", "ciphertext", "is_revealed", "created_at"]

    def has_add_permission(self, request):
        return False