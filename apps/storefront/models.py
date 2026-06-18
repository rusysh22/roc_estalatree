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

    class Meta:
        ordering = ["slug"]

    def __str__(self):
        return f"{self.title} (/{self.slug}/)"


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
