"""Root URL configuration."""
from django.contrib import admin
from django.urls import include, path

from api.v1 import api as ninja_api

# Access surfaces:
#   /admin/      Django Admin — Superadmin only
#   /console/    Operator Console (custom HTMX)
#   /dashboard/  Customer Dashboard (custom HTMX)
#   /            Storefront (link-in-bio + product pages + checkout)
#   /v1/         Activation API (Django Ninja)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("v1/", ninja_api.urls),
    path("console/", include("apps.console.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("billing/", include("apps.billing.urls")),
    path("seller/", include("apps.seller.urls", namespace="seller")),
    path("", include("apps.storefront.urls")),
]
