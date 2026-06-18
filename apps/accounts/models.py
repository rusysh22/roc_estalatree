"""Accounts models: SellerProfile (multi-tenant-ready) and Customer profile."""
from django.contrib.auth import get_user_model
from django.db import models

from apps.core.models import TimestampedModel

User = get_user_model()


class SellerProfile(TimestampedModel):
    """Merchant / seller entity. Single row in single-merchant mode. See ADR-005."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Seller Profile"

    def __str__(self) -> str:
        return self.name


class Customer(TimestampedModel):
    """Extended profile for a buying user (OneToOne to Django User)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="customer")
    wa_number = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Customer"

    def __str__(self) -> str:
        return self.user.email