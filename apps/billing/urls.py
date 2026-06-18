"""Billing URL patterns — webhook receiver + checkout callbacks."""
from django.urls import path

from apps.billing.views import duitku_webhook

app_name = "billing"

urlpatterns = [
    path("webhook/duitku/", duitku_webhook, name="duitku_webhook"),
]
