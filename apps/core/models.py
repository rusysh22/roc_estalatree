"""Core domain models: base abstracts, AuditLog, Setting."""
from django.contrib.auth import get_user_model
from django.db import models


class TimestampedModel(models.Model):
    """Abstract base: created_at + updated_at on every model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SellerScopedModel(TimestampedModel):
    """Abstract base for business entities scoped to a seller (multi-tenant ready).

    Single-merchant now: seller is nullable (one default row). See ADR-005.
    """

    seller = models.ForeignKey(
        "accounts.SellerProfile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True


class AuditLog(models.Model):
    """Immutable audit trail. Never update or delete rows — enforced at model level."""

    actor = models.ForeignKey(
        get_user_model(),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=100, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["actor", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise TypeError("AuditLog entries are immutable — updates are not allowed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("AuditLog entries are immutable — deletion is not allowed.")

    def __str__(self) -> str:
        return f"{self.actor} · {self.action} · {self.created_at:%Y-%m-%d %H:%M}"


class Setting(models.Model):
    """Global key-value configuration store."""

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.key} = {self.value}"

    @classmethod
    def get(cls, key: str, default: str = "") -> str:
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default
