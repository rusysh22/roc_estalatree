"""Notification dispatch — one entry point, one channel per notification (ADR-022).

`notify()` sends a notification on the customer's effective channel and records
a `NotificationDelivery` outbox row. `notify_wa_copy()` is for value-document
handlers whose authoritative email is dispatched separately (HTML receipt): it
adds a WhatsApp copy only when WA is the chosen channel.

Effective channel = `Customer.resolve_channel()` with a final WA-suppression gate
(a number that replied STOP falls back to email).
"""
import logging

from apps.core.models import NotificationChannel
from apps.notifications.whatsapp import normalize_number, wa_suppressed

logger = logging.getLogger(__name__)


def effective_channel(customer) -> str:
    channel = customer.resolve_channel()
    if channel == NotificationChannel.WHATSAPP and wa_suppressed(customer.wa_number):
        return NotificationChannel.EMAIL
    return channel


def _record(customer, *, event, channel, recipient, wa_text="", email_subject="", email_body=""):
    from apps.notifications.models import NotificationDelivery
    return NotificationDelivery.objects.create(
        customer=customer, event=event, channel=channel, recipient=recipient,
        wa_text=wa_text, email_subject=email_subject, email_body=email_body,
    )


def notify(customer, *, event, wa_text, email_subject, email_body):
    """Send one notification on the customer's effective channel."""
    from apps.notifications.tasks import deliver_email, deliver_whatsapp

    channel = effective_channel(customer)
    if channel == NotificationChannel.WHATSAPP:
        number = normalize_number(customer.wa_number)
        delivery = _record(
            customer, event=event, channel=channel, recipient=number,
            wa_text=wa_text, email_subject=email_subject, email_body=email_body,
        )
        deliver_whatsapp.delay(number, wa_text, delivery_id=delivery.pk)
        return delivery

    delivery = _record(
        customer, event=event, channel=channel, recipient=customer.notify_email_address,
        email_subject=email_subject, email_body=email_body,
    )
    deliver_email.delay(customer.notify_email_address, email_subject, email_body)
    return delivery


def notify_wa_copy(customer, *, event, wa_text):
    """Push a WhatsApp copy of a value-document notification, only when WA is chosen.

    The authoritative document is emailed by the caller (HTML receipt task).
    """
    if effective_channel(customer) != NotificationChannel.WHATSAPP:
        return None

    from apps.notifications.tasks import deliver_whatsapp

    number = normalize_number(customer.wa_number)
    delivery = _record(customer, event=event, channel=NotificationChannel.WHATSAPP,
                       recipient=number, wa_text=wa_text)
    deliver_whatsapp.delay(number, wa_text, delivery_id=delivery.pk)
    return delivery


def fallback_delivery_to_email(delivery) -> bool:
    """Re-send a failed WhatsApp delivery as email. Returns True if an email was queued."""
    from apps.notifications.models import NotificationDelivery
    from apps.notifications.tasks import deliver_email

    if delivery.channel != NotificationChannel.WHATSAPP:
        return False
    if delivery.status == NotificationDelivery.Status.FALLBACK_SENT:
        return False
    if not (delivery.email_body and delivery.customer_id):
        return False

    email = delivery.customer.notify_email_address
    deliver_email.delay(email, delivery.email_subject or "Notification", delivery.email_body)
    delivery.status = NotificationDelivery.Status.FALLBACK_SENT
    delivery.save(update_fields=["status", "updated_at"])
    logger.info("fallback_delivery_to_email: delivery %s → email %s", delivery.pk, email)
    return True
