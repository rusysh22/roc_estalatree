"""Provisioning models: Deliverable, Entitlement, Grant, Secret.

The generalized fulfillment layer. See docs/15-provisioning-and-entitlements.md.

Flow:
  Plan → Deliverable(s) + Entitlement(s)
  Order paid → Provisioner.provision(order) → Grant
  Subscription state change → Provisioner.suspend/resume/revoke(grant)
"""
from django.db import models

from apps.core.models import TimestampedModel


class Deliverable(TimestampedModel):
    """Declares what a Plan provides (type + config). One Plan may have several."""

    class Type(models.TextChoices):
        LICENSE_KEY = "license_key", "License Key"
        CREDENTIALS = "credentials", "Credentials"
        ACCOUNT = "account", "Account"
        DOWNLOAD = "download", "Download"
        ACCESS_LINK = "access_link", "Access Link"
        API_KEY = "api_key", "API Key"
        MANUAL = "manual", "Manual"

    plan = models.ForeignKey("catalog.Plan", on_delete=models.PROTECT, related_name="deliverables")
    type = models.CharField(max_length=20, choices=Type.choices)
    config = models.JSONField(default=dict, blank=True, help_text="Provisioner-specific config")

    def __str__(self) -> str:
        return f"{self.get_type_display()} for {self.plan}"


class Entitlement(TimestampedModel):
    """Named feature capability. Attached to Plans; inherited by Grants.

    Never branch on plan name — check grant.has_entitlement("KEY") instead.
    See ADR-010.
    """

    key = models.CharField(max_length=100, help_text='e.g. "PRO_EXPORT", "MAX_PROJECTS"')
    name = models.CharField(max_length=200)
    value = models.CharField(max_length=200, blank=True, help_text='e.g. "10" for MAX_PROJECTS')
    plans = models.ManyToManyField("catalog.Plan", related_name="entitlements", blank=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        if self.value:
            return f"{self.key}={self.value}"
        return self.key


class Grant(TimestampedModel):
    """Issued artifact + lifecycle. The customer's proof of purchase.

    Each Grant is produced by a Provisioner when an Order is paid.
    Lifecycle (suspend/resume/revoke) is propagated from Subscription state.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.PROTECT, related_name="grants"
    )
    subscription = models.ForeignKey(
        "billing.Subscription",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="grants",
    )
    deliverable = models.ForeignKey(Deliverable, on_delete=models.PROTECT, related_name="grants")
    type = models.CharField(
        max_length=20,
        choices=Deliverable.Type.choices,
        help_text="Denormalized from deliverable.type for fast lookup",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    payload = models.JSONField(
        default=dict,
        blank=True,
        help_text='Artifact reference, e.g. {"license_id": 42}',
    )
    valid_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["type", "status"]),
        ]

    def __str__(self) -> str:
        return f"Grant({self.type}/{self.status}) → {self.customer}"

    def has_entitlement(self, key: str) -> bool:
        """Check if the grant's plan carries a given entitlement key."""
        plan = self.deliverable.plan
        return plan.entitlements.filter(key=key).exists()

    def get_entitlements(self) -> dict[str, str]:
        """Return all entitlements as {key: value} dict for API responses."""
        return dict(
            self.deliverable.plan.entitlements.values_list("key", "value")
        )


class Secret(models.Model):
    """Encrypted credential for credentials/api_key grants. Shown once, stored ciphertext.

    Encryption approach: TODO(decision) — Fernet/KMS (see STATUS.md open questions).
    ciphertext field stores the raw encrypted bytes as a base64 string.
    """

    grant = models.OneToOneField(Grant, on_delete=models.CASCADE, related_name="secret")
    ciphertext = models.TextField(help_text="Encrypted credential — Fernet base64")
    is_revealed = models.BooleanField(default=False)
    rotated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        revealed = "revealed" if self.is_revealed else "unrevealed"
        return f"Secret({self.grant}) [{revealed}]"