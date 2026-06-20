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
    coupon = models.ForeignKey(
        "billing.Coupon",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    discount = models.PositiveBigIntegerField(default=0, help_text="Coupon discount applied (IDR)")
    invoice_number = models.PositiveIntegerField(
        null=True, blank=True, unique=True,
        help_text="Sequential invoice number, assigned when order is marked PAID",
    )
    custom_fields = models.JSONField(
        default=dict, blank=True,
        help_text="Buyer answers to ProductQuestion intake fields",
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


class Coupon(TimestampedModel):
    """Checkout-time discount voucher. Supports percent and fixed-IDR discounts."""

    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percent (%)"
        FIXED = "fixed", "Fixed (Rp)"

    code = models.CharField(max_length=50, unique=True, db_index=True)
    discount_type = models.CharField(
        max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT
    )
    value = models.PositiveBigIntegerField(help_text="Percent 1–100 or fixed Rp amount")
    min_order = models.PositiveBigIntegerField(default=0, help_text="Min order amount to apply (0 = no minimum)")
    max_discount = models.PositiveBigIntegerField(default=0, help_text="Cap on discount IDR (0 = no cap, percent type)")
    usage_limit = models.PositiveIntegerField(default=0, help_text="Max redemptions (0 = unlimited)")
    used_count = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    seller = models.ForeignKey(
        "accounts.SellerProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="coupons",
    )
    plans = models.ManyToManyField("catalog.Plan", blank=True, help_text="Restrict to specific plans (empty = all)")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        suffix = f"{self.value}%" if self.discount_type == self.DiscountType.PERCENT else f"Rp{self.value:,}"
        return f"{self.code} ({suffix})"

    def compute_discount(self, order_amount: int) -> int:
        """Return discount IDR for the given order amount."""
        if self.discount_type == self.DiscountType.PERCENT:
            discount = order_amount * self.value // 100
            if self.max_discount > 0:
                discount = min(discount, self.max_discount)
        else:
            discount = self.value
        return min(discount, order_amount)

    def is_valid_for(self, plan=None) -> tuple[bool, str]:
        """Returns (valid, error_message)."""
        from django.utils import timezone
        if not self.is_active:
            return False, "Coupon is not active."
        now = timezone.now()
        if self.valid_from and now < self.valid_from:
            return False, "Coupon is not yet valid."
        if self.valid_until and now > self.valid_until:
            return False, "Coupon has expired."
        if self.usage_limit > 0 and self.used_count >= self.usage_limit:
            return False, "Coupon usage limit reached."
        if plan and self.plans.exists() and not self.plans.filter(pk=plan.pk).exists():
            return False, "Coupon is not valid for this plan."
        return True, ""


# ── Seller earnings & payouts ──────────────────────────────────────────────────

class SellerEarning(TimestampedModel):
    """Platform records one earning row per paid order.

    gross = order.amount, commission = platform fee cut, net = gross - commission.
    Immutable once created (no update/delete — same rule as LedgerEntry/AuditLog).
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID_OUT = "paid_out", "Paid Out"
        VOIDED = "voided", "Voided"

    seller = models.ForeignKey(
        "accounts.SellerProfile", on_delete=models.PROTECT, related_name="earnings"
    )
    order = models.OneToOneField(
        "billing.Order", on_delete=models.PROTECT, related_name="seller_earning"
    )
    gross = models.PositiveBigIntegerField(help_text="Order amount (IDR)")
    commission = models.PositiveBigIntegerField(default=0, help_text="Platform fee (IDR)")
    net = models.PositiveBigIntegerField(help_text="Seller receives (IDR)")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["seller", "status"])]

    def __str__(self) -> str:
        return f"Earning #{self.pk} for {self.seller} — Rp{self.net:,} [{self.status}]"


class SellerPayout(TimestampedModel):
    """Seller requests a withdrawal of their pending earnings."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"

    seller = models.ForeignKey(
        "accounts.SellerProfile", on_delete=models.PROTECT, related_name="payouts"
    )
    amount = models.PositiveBigIntegerField(help_text="Requested withdrawal (IDR)")
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    account_name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["seller", "status"])]

    def __str__(self) -> str:
        return f"Payout #{self.pk} {self.seller} Rp{self.amount:,} [{self.status}]"


# ── Affiliate program ─────────────────────────────────────────────────────────

class AffiliateLink(TimestampedModel):
    """A unique referral code created by a seller (or the platform owner).

    When a buyer visits the store with ?ref=<code> the code is stored in their
    session and an AffiliateCommission is recorded on purchase.
    """

    seller = models.ForeignKey(
        "accounts.SellerProfile", on_delete=models.PROTECT, related_name="affiliate_links",
        help_text="Product seller who owns this link programme",
    )
    affiliate_seller = models.ForeignKey(
        "accounts.SellerProfile", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="affiliate_promotions",
        help_text="The promoter (another seller). Null = external promoter.",
    )
    product = models.ForeignKey(
        "catalog.Product", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="affiliate_links",
        help_text="Restrict to this product. Null = applies to all seller products.",
    )
    code = models.CharField(max_length=30, unique=True, db_index=True)
    commission_rate = models.PositiveSmallIntegerField(
        default=10, help_text="Commission % of net order amount for the affiliate"
    )
    clicks = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    label = models.CharField(max_length=100, blank=True, help_text="Internal label for tracking")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Ref:{self.code} ({self.commission_rate}%) for {self.seller}"


class AffiliateCommission(TimestampedModel):
    """Commission earned per paid order via an AffiliateLink.

    Immutable once created.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID_OUT = "paid_out", "Paid Out"
        VOIDED = "voided", "Voided"

    link = models.ForeignKey(AffiliateLink, on_delete=models.PROTECT, related_name="commissions")
    order = models.OneToOneField(
        "billing.Order", on_delete=models.PROTECT, related_name="affiliate_commission"
    )
    amount = models.PositiveBigIntegerField(help_text="Commission earned (IDR)")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Commission #{self.pk} {self.link.code} Rp{self.amount:,} [{self.status}]"