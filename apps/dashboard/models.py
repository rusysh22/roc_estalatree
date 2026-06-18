"""Customer Dashboard models.

RefundRequest: customer-initiated refund for a paid Order.
Status machine: PENDING → APPROVED (wallet credit issued) | REJECTED.
Admin processes these from the Operator Console work queue (Phase 10).
"""
from django.db import models

from apps.core.models import TimestampedModel


class RefundRequest(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    customer = models.ForeignKey(
        "accounts.Customer",
        on_delete=models.CASCADE,
        related_name="refund_requests",
    )
    order = models.ForeignKey(
        "billing.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="refund_requests",
    )
    reason = models.TextField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    admin_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund #{self.pk} [{self.status}] — {self.customer}"
