from django.contrib import admin

from apps.wallet.models import LedgerEntry, Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ["customer", "balance", "updated_at"]
    search_fields = ["customer__user__email"]
    readonly_fields = ["balance"]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ["created_at", "wallet", "type", "amount", "balance_after", "ref"]
    list_filter = ["type"]
    search_fields = ["ref", "wallet__customer__user__email"]
    readonly_fields = ["wallet", "type", "amount", "balance_after", "ref", "note", "created_at"]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False