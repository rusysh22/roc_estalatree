"""Seller Dashboard URL patterns — /seller/ (seller access)."""
from django.urls import path

from apps.seller import views

app_name = "seller"

urlpatterns = [
    path("", views.home, name="home"),
    path("products/", views.products, name="products"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:product_pk>/plans/new/", views.plan_create, name="plan_create"),
    path("products/<int:product_pk>/plans/<int:plan_pk>/edit/", views.plan_edit, name="plan_edit"),
    path("products/<int:product_pk>/plans/<int:plan_pk>/entitlements/add/", views.entitlement_add, name="entitlement_add"),
    path("products/<int:product_pk>/plans/<int:plan_pk>/entitlements/<int:ent_pk>/remove/", views.entitlement_remove, name="entitlement_remove"),
    path("products/<int:product_pk>/questions/add/", views.question_add, name="question_add"),
    path("products/<int:product_pk>/questions/<int:question_pk>/remove/", views.question_remove, name="question_remove"),
    path("orders/", views.orders, name="orders"),
    path("store/", views.store, name="store"),
    path("store/blocks/add/", views.block_add, name="block_add"),
    path("store/blocks/<int:block_pk>/remove/", views.block_remove, name="block_remove"),
    path("vouchers/", views.vouchers, name="vouchers"),
    path("vouchers/new/", views.voucher_create, name="voucher_create"),
    path("vouchers/<int:pk>/edit/", views.voucher_edit, name="voucher_edit"),
    path("vouchers/<int:pk>/toggle/", views.voucher_toggle, name="voucher_toggle"),
    path("broadcast/", views.broadcast, name="broadcast"),
    path("settings/", views.settings, name="settings"),
    path("apply/", views.apply, name="apply"),
]
