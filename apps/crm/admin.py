from django.contrib import admin

from apps.crm.models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ["public_id", "name", "contact", "product", "status", "assigned_to", "created_at"]
    list_filter = ["status"]
    search_fields = ["name", "contact", "public_id"]
    raw_id_fields = ["product", "assigned_to"]
    readonly_fields = ["public_id"]