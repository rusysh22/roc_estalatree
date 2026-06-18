"""Licensing models: License and Installation.

License is the specialization of a license_key Grant — it links back to its Grant
and holds the activation key + seat management. See docs/15-provisioning-and-entitlements.md §15.2.

Status transitions per docs/14-state-machines.md — enforced in services.
"""
from django.db import models

from apps.core.models import TimestampedModel
from apps.licensing.utils import assign_unique_license_key


class License(TimestampedModel):
    """OSS product usage right: a license key + seat limit + lifecycle status."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    key = models.CharField(
        max_length=14,
        unique=True,
        editable=False,
        help_text="XXXX-XXXX-XXXX Crockford Base32 (ADR-007)",
    )
    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.PROTECT, related_name="licenses"
    )
    plan = models.ForeignKey("catalog.Plan", on_delete=models.PROTECT, related_name="licenses")
    subscription = models.ForeignKey(
        "billing.Subscription",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="licenses",
    )
    grant = models.OneToOneField(
        "provisioning.Grant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    seat_limit = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # L1 fix: key is unique=True so no separate Index needed
            models.Index(fields=["customer", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.key} [{self.status}]"

    def save(self, *args, **kwargs):
        if not self.key:
            assign_unique_license_key(self)
        super().save(*args, **kwargs)

    @property
    def active_seat_count(self) -> int:
        return self.installations.filter(status=Installation.Status.ACTIVE).count()

    @property
    def seats_available(self) -> bool:
        return self.active_seat_count < self.seat_limit


class Installation(TimestampedModel):
    """A registered OSS product instance (device/machine). Consumes one seat."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DEACTIVATED = "deactivated", "Deactivated"

    license = models.ForeignKey(License, on_delete=models.CASCADE, related_name="installations")
    fingerprint = models.CharField(max_length=200, help_text="Unique device/machine identity")
    name = models.CharField(max_length=200, blank=True, help_text="User-provided device label")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    last_seen = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-activated_at"]
        indexes = [
            models.Index(fields=["license", "status"]),
            models.Index(fields=["fingerprint"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["license", "fingerprint"],
                condition=models.Q(status="active"),
                name="unique_active_fingerprint_per_license",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name or self.fingerprint[:12]} [{self.status}]"