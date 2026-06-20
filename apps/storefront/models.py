"""Storefront models — link-in-bio page + blocks.

Single-merchant MVP: one StorePage (the root /). Slug-based pages are
available for future multi-seller expansion.

Block types for MVP: product, link, heading, text.
"""
from django.db import models

from apps.core.models import TimestampedModel


class StorePage(TimestampedModel):
    """The public shareable store page. One per seller in single-merchant mode."""

    slug = models.SlugField(unique=True, max_length=100)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    avatar_url = models.URLField(blank=True)
    is_published = models.BooleanField(default=False)
    theme = models.JSONField(default=dict, blank=True)
    seller = models.OneToOneField(
        "accounts.SellerProfile",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="store_page",
    )

    class Meta:
        ordering = ["slug"]

    def __str__(self):
        return f"{self.title} (/{self.slug}/)"


class PageEvent(models.Model):
    """Lightweight analytics event. Each row = one page view or click.

    Kept intentionally simple — no PII beyond session key.
    Aggregated in seller analytics views.
    """

    class EventType(models.TextChoices):
        PAGE_VIEW = "page_view", "Page view"
        PRODUCT_VIEW = "product_view", "Product view"
        CHECKOUT_START = "checkout_start", "Checkout start"
        ORDER_PAID = "order_paid", "Order paid"

    event = models.CharField(max_length=30, choices=EventType.choices)
    product = models.ForeignKey(
        "catalog.Product",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="page_events",
    )
    plan = models.ForeignKey(
        "catalog.Plan",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="page_events",
    )
    session_key = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event", "created_at"]),
            models.Index(fields=["product", "event"]),
        ]

    def __str__(self) -> str:
        return f"{self.event} @ {self.created_at:%Y-%m-%d}"


class Block(TimestampedModel):
    """An ordered content unit on a StorePage."""

    class Type(models.TextChoices):
        PRODUCT = "product", "Product"
        LINK = "link", "Link"
        HEADING = "heading", "Heading"
        TEXT = "text", "Text"

    store_page = models.ForeignKey(
        StorePage, on_delete=models.CASCADE, related_name="blocks"
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    position = models.PositiveSmallIntegerField(default=0)
    config = models.JSONField(default=dict, blank=True)
    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blocks",
    )
    is_visible = models.BooleanField(default=True)

    class Meta:
        ordering = ["store_page", "position"]

    def __str__(self):
        return f"{self.type} @ pos {self.position} — {self.store_page.slug}"
