"""Notification models.

NotificationLog: dedup record that prevents duplicate dispatches when
Celery retries a task or an hourly reminder job re-runs before the next window.

Dedup key conventions:
  reminder:{sub_id}:{period_end_date}:{h3|h1}:{whatsapp|email}
  event:{event_name}:{customer_id}:{ref}
"""
from django.db import models

from apps.core.models import TimestampedModel


class NotificationLog(TimestampedModel):
    """Immutable record of a dispatched notification.

    The unique dedup_key prevents sending the same notification twice even
    when the hourly job overlaps or a Celery task is retried after delivery.
    """

    CHANNEL_WHATSAPP = "whatsapp"
    CHANNEL_EMAIL = "email"

    dedup_key = models.CharField(max_length=255, unique=True)
    channel = models.CharField(max_length=20)
    recipient = models.CharField(max_length=255)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel}:{self.recipient} [{self.dedup_key}]"


class EmailSuppression(TimestampedModel):
    """An address we must stop emailing (hard bounce, spam complaint, or manual block).

    Populated by the ESP's bounce webhook (see apps.notifications.views) and
    checked before every send in apps.notifications.tasks — protects sender
    reputation from repeatedly hitting known-bad addresses.
    """

    class Reason(models.TextChoices):
        HARD_BOUNCE = "hard_bounce", "Hard bounce"
        SPAM_COMPLAINT = "spam_complaint", "Spam complaint"
        MANUAL = "manual", "Manually suppressed"

    email = models.EmailField(unique=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    detail = models.TextField(blank=True, help_text="Raw reason/diagnostic from the ESP, if any")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} [{self.reason}]"
