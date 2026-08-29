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


class WhatsAppSuppression(TimestampedModel):
    """A WhatsApp number we must stop messaging (ADR-022).

    Populated by the kirim.chat inbound webhook when a recipient replies STOP,
    or manually. Checked in the dispatch layer before every WA send; a
    suppressed number makes the customer's effective channel fall back to email.
    """

    class Reason(models.TextChoices):
        OPT_OUT = "opt_out", "Replied STOP"
        INVALID_NUMBER = "invalid_number", "Invalid / unreachable number"
        COMPLAINT = "complaint", "Complaint"
        MANUAL = "manual", "Manually suppressed"

    number = models.CharField(max_length=20, unique=True, help_text="Normalized (62…) number.")
    reason = models.CharField(max_length=20, choices=Reason.choices)
    detail = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} [{self.reason}]"


class WhatsAppOTP(TimestampedModel):
    """One-time code for verifying a customer's WhatsApp number (ADR-022, N.4).

    Only the hash of the code is stored. A code is valid until `expires_at`,
    for at most `MAX_ATTEMPTS` guesses, and only while `consumed_at` is null.
    """

    MAX_ATTEMPTS = 5

    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.CASCADE, related_name="wa_otps"
    )
    number = models.CharField(max_length=20)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "number", "consumed_at"])]

    def __str__(self):
        return f"OTP {self.number} for customer {self.customer_id}"


class NotificationDelivery(TimestampedModel):
    """Outbox row: one per notification we hand to a channel.

    Stores enough to (a) track delivery status from provider webhooks and
    (b) fall back to email if a WhatsApp send fails. Value-document emails
    (HTML receipts) are dispatched by their own tasks and are not tracked here.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent to provider"
        DELIVERED = "delivered", "Delivered"
        READ = "read", "Read"
        FAILED = "failed", "Failed"
        FALLBACK_SENT = "fallback_sent", "Fell back to email"

    customer = models.ForeignKey(
        "accounts.Customer", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="notifications",
    )
    event = models.CharField(max_length=80, blank=True)
    channel = models.CharField(max_length=20)
    recipient = models.CharField(max_length=255)

    # Retained so a failed WA send can be re-sent as email.
    wa_text = models.TextField(blank=True)
    email_subject = models.CharField(max_length=255, blank=True)
    email_body = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    provider = models.CharField(max_length=20, blank=True)
    provider_msg_id = models.CharField(max_length=128, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["provider_msg_id"])]
        verbose_name_plural = "Notification deliveries"

    def __str__(self):
        return f"{self.channel}:{self.recipient} {self.event} [{self.status}]"
