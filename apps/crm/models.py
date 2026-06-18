"""CRM models: Lead (prospect from Contact-type product flow)."""
from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel
from apps.core.utils import generate_public_id


class Lead(TimestampedModel):
    """A prospect who clicked a Contact-type product. Assigned to an operator for follow-up."""

    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In Progress"
        CLOSING = "closing", "Closing"
        WON = "won", "Won"
        LOST = "lost", "Lost"

    public_id = models.CharField(max_length=40, unique=True, editable=False)
    name = models.CharField(max_length=200)
    contact = models.CharField(max_length=200, help_text="WhatsApp number or email")
    product = models.ForeignKey(
        "catalog.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leads",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    notes = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_leads",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "assigned_to"])]

    def __str__(self) -> str:
        return f"{self.public_id} {self.name} [{self.status}]"

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = generate_public_id("lead_")
        super().save(*args, **kwargs)