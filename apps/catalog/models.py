"""Catalog models: Product, Plan, ProductQuestion, ProductReview."""
from django.db import models
from django.utils.text import slugify

from apps.core.models import SellerScopedModel, TimestampedModel


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
    cover_image_url = models.URLField(blank=True, default="", help_text="Cover image URL shown on the storefront (optional)")
    wa_number = models.CharField(max_length=20, blank=True, help_text="WhatsApp for contact-type products")
    purchase_button_label = models.CharField(
        max_length=60, blank=True, default="",
        help_text="Override Buy button text (default: 'Buy Now')",
    )

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
    sale_price = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="Strike-through original price shown on storefront"
    )
    pwyw = models.BooleanField(default=False, help_text="Pay-what-you-want: buyer sets the price")
    min_price = models.PositiveBigIntegerField(default=0, help_text="Minimum price for PWYW (0 = no minimum)")
    stock_quantity = models.PositiveIntegerField(null=True, blank=True, help_text="Stock limit (null = unlimited)")

    class Meta:
        ordering = ["product", "sort_order", "price"]

    def __str__(self) -> str:
        return f"{self.product.name} / {self.name}"


class ProductQuestion(TimestampedModel):
    """A custom intake question shown on the checkout page."""

    class FieldType(models.TextChoices):
        TEXT = "text", "Short text"
        EMAIL = "email", "Email"
        PHONE = "phone", "Phone number"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="questions")
    label = models.CharField(max_length=200)
    field_type = models.CharField(max_length=20, choices=FieldType.choices, default=FieldType.TEXT)
    required = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["product", "sort_order"]

    def __str__(self) -> str:
        return f"{self.product.name} / Q: {self.label}"


class ProductReview(TimestampedModel):
    """A buyer review left after a successful purchase."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    order = models.OneToOneField("billing.Order", on_delete=models.CASCADE, related_name="review")
    rating = models.PositiveSmallIntegerField(
        help_text="1–5 stars",
        choices=[(i, str(i)) for i in range(1, 6)],
    )
    text = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.product.name} / {self.rating}★ by {self.order.customer}"


class CourseModule(TimestampedModel):
    """An ordered section/chapter within a course product."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=200)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["product", "sort_order"]

    def __str__(self) -> str:
        return f"{self.product.name} / Module: {self.title}"


class CourseLesson(TimestampedModel):
    """A single lesson (video, text, or file) within a CourseModule."""

    class LessonType(models.TextChoices):
        VIDEO = "video", "Video"
        TEXT = "text", "Text"
        FILE = "file", "File download"

    module = models.ForeignKey(CourseModule, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    lesson_type = models.CharField(max_length=20, choices=LessonType.choices, default=LessonType.TEXT)
    content = models.TextField(blank=True, help_text="Text content or video embed URL")
    file_url = models.URLField(blank=True, help_text="Direct file URL (for file lessons)")
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_preview = models.BooleanField(default=False, help_text="Accessible without purchase (free preview)")

    class Meta:
        ordering = ["module", "sort_order"]

    def __str__(self) -> str:
        return f"{self.module.product.name} / {self.module.title} / {self.title}"


class CourseProgress(TimestampedModel):
    """Tracks which lessons a customer has completed."""

    customer = models.ForeignKey("accounts.Customer", on_delete=models.CASCADE, related_name="course_progress")
    lesson = models.ForeignKey(CourseLesson, on_delete=models.CASCADE, related_name="progress")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("customer", "lesson")]
        ordering = ["-completed_at"]

    def __str__(self) -> str:
        return f"{self.customer} completed {self.lesson.title}"