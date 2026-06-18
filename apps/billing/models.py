"""Billing models: Order, TopUp, PaymentWebhook, Subscription.

Status transitions per 14-state-machines.md — enforced in services, not models.
public_id values are generated via apps.core.utils.generate_public_id.
"""
from django.db import models

from apps.core.models import TimestampedModel
from apps.core.utils import assign_unique_public_id


class TopUp(TimestampedModel):
    """A Duitku invoice that funds a customer wallet. See ADR-003."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        EXPIRED = "expired", "Expired"
        FAILED = "failed", "Failed"

    class Gateway(models.TextChoices):
        DUITKU = "duitku", "Duitku"

    public_id = models.CharField(max_length=40, unique=True, editable=False)
    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.PROTECT, related_name="topups"
    )
    amount = models.PositiveBigIntegerField(help_text="Whole IDR")
    bonus = models.PositiveBigIntegerField(default=0, help_text="Promotional bonus IDR")
    gateway = models.CharField(max_length=20, choices=Gateway.choices, default=Gateway.DUITKU)
    gateway_ref = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    ledger_entry = models.OneToOneField(
        "wallet.LedgerEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="topup",
    )
    checkout_order = models.OneToOneField(
        "billing.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="funding_topup",
        help_text="Top-up-and-buy: complete this Order after TopUp is credited",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "status"])]

    def __str__(self) -> str:
        return f"{self.public_id} Rp{self.amount:,} [{self.status}]"

    def save(self, *args, **kwargs):
        if not self.public_id:
            assign_unique_public_id(self, "top_")
        super().save(*args, **kwargs)


class Order(TimestampedModel):
    """A balance-deduction purchase of a plan. See billing flow in 05-flows.md."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    public_id = models.CharField(max_length=40, unique=True, editable=False)
    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.PROTECT, related_name="orders"
    )
    plan = models.ForeignKey("catalog.Plan", on_delete=models.PROTECT, related_name="orders")
    amount = models.PositiveBigIntegerField(help_text="IDR charged (snapshot of plan price)")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    ledger_entry = models.OneToOneField(
        "wallet.LedgerEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order",
    )
    idempotency_key = models.CharField(
        max_length=200,
        unique=True,
        null=True,
        blank=True,
        help_text="Caller-supplied key for safe checkout retry",
    )
    subscription = models.ForeignKey(
        "billing.Subscription",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
        help_text="Subscription created by this Order (recurring plans only)",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "status"])]

    def __str__(self) -> str:
        return f"{self.public_id} {self.plan} [{self.status}]"

    def save(self, *args, **kwargs):
        if not self.public_id:
            assign_unique_public_id(self, "ord_")
        super().save(*args, **kwargs)


class PaymentWebhook(models.Model):
    """Raw webhook payload log — idempotency gate for all gateway callbacks."""

    idempotency_key = models.CharField(max_length=200, unique=True)
    gateway = models.CharField(max_length=20)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        status = "processed" if self.processed_at else "pending"
        return f"[{self.gateway}] {self.idempotency_key} ({status})"


class Subscription(TimestampedModel):
    """Recurring access right. Renewed by balance auto-deduct. See ADR-002."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        GRACE = "grace", "Grace"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.PROTECT, related_name="subscriptions"
    )
    plan = models.ForeignKey("catalog.Plan", on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    current_period_end = models.DateTimeField()
    auto_renew = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "status"])]

    def __str__(self) -> str:
        return f"Sub({self.customer} / {self.plan}) [{self.status}]"