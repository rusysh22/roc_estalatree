from django.contrib import admin

from apps.catalog.models import Plan, Product


class PlanInline(admin.TabularInline):
    model = Plan
    extra = 0
    fields = ["name", "price", "interval", "seat_limit", "is_active", "sort_order"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "type", "visibility", "slug", "created_at"]
    list_filter = ["type", "visibility"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [PlanInline]


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["name", "product", "price", "interval", "seat_limit", "is_active"]
    list_filter = ["interval", "is_active"]
    search_fields = ["name", "product__name"]
    raw_id_fields = ["product"]