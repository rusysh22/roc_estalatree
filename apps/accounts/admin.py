from django.contrib import admin

from apps.accounts.models import Customer, SellerProfile


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "created_at"]
    search_fields = ["name", "slug"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["user", "wa_number", "created_at"]
    search_fields = ["user__email", "wa_number"]
    raw_id_fields = ["user"]