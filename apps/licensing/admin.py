from django.contrib import admin

from apps.licensing.models import Installation, License


class InstallationInline(admin.TabularInline):
    model = Installation
    extra = 0
    readonly_fields = ["fingerprint", "status", "last_seen", "activated_at"]
    fields = ["fingerprint", "name", "status", "last_seen", "activated_at"]


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    list_display = ["key", "customer", "plan", "status", "seat_limit", "active_seat_count"]
    list_filter = ["status"]
    search_fields = ["key", "customer__user__email", "plan__name"]
    readonly_fields = ["key"]
    inlines = [InstallationInline]

    @admin.display(description="Active seats")
    def active_seat_count(self, obj):
        return obj.active_seat_count


@admin.register(Installation)
class InstallationAdmin(admin.ModelAdmin):
    list_display = ["fingerprint", "license", "name", "status", "last_seen"]
    list_filter = ["status"]
    search_fields = ["fingerprint", "license__key"]
    readonly_fields = ["fingerprint", "activated_at"]