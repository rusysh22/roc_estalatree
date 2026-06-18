from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import Customer, SellerProfile, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["email", "is_staff", "is_active", "date_joined"]
    list_filter = ["is_staff", "is_active"]
    search_fields = ["email"]
    ordering = ["email"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("date_joined", "last_login")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )
    # BaseUserAdmin expects username_field; override to email
    filter_horizontal = ("groups", "user_permissions")


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "created_at"]
    search_fields = ["name", "slug"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["user", "wa_number", "created_at"]
    search_fields = ["user__email", "wa_number"]
    raw_id_fields = ["user"]