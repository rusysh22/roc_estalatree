"""Customer Dashboard URL patterns — /dashboard/."""
from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("wallet/", views.wallet, name="wallet"),
    path("wallet/ledger/", views.ledger_partial, name="ledger_partial"),
    path("products/", views.products, name="products"),
    path("devices/", views.devices, name="devices"),
    path("devices/<int:pk>/deactivate/", views.deactivate_device, name="deactivate_device"),
    path("subscriptions/", views.subscriptions, name="subscriptions"),
    path("subscriptions/<int:pk>/auto-renew/", views.toggle_auto_renew, name="toggle_auto_renew"),
    path("invoices/", views.invoices, name="invoices"),
    path("profile/", views.profile, name="profile"),
    path("support/", views.support, name="support"),
    path("orders/<pk>/refund/", views.refund_request, name="refund_request"),
    path("grants/<int:pk>/reveal/", views.reveal_secret, name="reveal_secret"),
]
