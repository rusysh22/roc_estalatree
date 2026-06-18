"""Catalog models: Product and Plan."""
from django.db import models
from django.utils.text import slugify

from apps.core.models import SellerScopedModel


class Product(SellerScopedModel):
    """A digital item available for sale on the storefront."""

    class Type(models.TextChoices):
        FREE = "free", "Free"
        ONE_TIME = "one_time", "One-time"
        RECURRING = "recurring", "Recurring"
        CONTACT = "contact", "Contact"

    class Visibility(models.TextChoices):
        DRAFT = "draft", "Draft"
        UNLISTED = "unlisted", "Unlisted"
        PUBLIC = "public", "Public"

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=220)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.ONE_TIME)
    visibility = models.CharField(
        max_length=20, choices=Visibility.choices, default=Visibility.DRAFT
    )
    description = models.TextField(blank=True)
    wa_number = models.CharField(max_length=20, blank=True, help_text="WhatsApp for contact-type products")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Plan(SellerScopedModel):
    """A purchasable variant of a Product (price, billing interval, seat limit)."""

    class Interval(models.TextChoices):
        NONE = "none", "None (one-time)"
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="plans")
    name = models.CharField(max_length=200)
    price = models.PositiveBigIntegerField(help_text="Whole IDR — no subunit")
    interval = models.CharField(
        max_length=20, choices=Interval.choices, default=Interval.NONE
    )
    seat_limit = models.PositiveIntegerField(default=1)
    features = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["product", "sort_order", "price"]

    def __str__(self) -> str:
        return f"{self.product.name} / {self.name}"