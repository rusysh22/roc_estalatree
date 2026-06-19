"""Operator Console URL patterns — /console/ (staff/superuser access)."""
from django.urls import path

from apps.console import views

app_name = "console"

urlpatterns = [
    # 10a
    path("setup/", views.setup, name="setup"),
    # 10b
    path("", views.cockpit, name="cockpit"),
    # 10c
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/<int:customer_pk>/", views.customer_360, name="customer_360"),
    path("customers/<int:customer_pk>/credit/", views.manual_credit, name="manual_credit"),
    path("subscriptions/<int:sub_pk>/extend/", views.extend_subscription, name="extend_subscription"),
    # 10c — Lead detail
    path("leads/<int:pk>/", views.lead_detail, name="lead_detail"),
    # 10d
    path("refund/<int:pk>/", views.refund_detail, name="refund_detail"),
    path("refund/<int:pk>/approve/", views.refund_approve, name="refund_approve"),
    path("refund/<int:pk>/reject/", views.refund_reject, name="refund_reject"),
    path("export/<str:model_name>/", views.export_csv, name="export_csv"),
    # 10e
    path("audit/", views.audit_log_view, name="audit_log"),
    path("settings/", views.settings_view, name="settings"),
]
