"""Billing URL patterns — webhook receiver."""
from django.urls import path

from apps.billing.views import sumopod_webhook

app_name = "billing"

urlpatterns = [
    path("webhook/sumopod/", sumopod_webhook, name="sumopod_webhook"),
]
