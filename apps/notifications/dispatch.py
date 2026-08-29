"""Notification dispatch — one entry point, one channel per notification (ADR-022).

`notify()` sends a notification on the customer's effective channel and records
a `NotificationDelivery` outbox row. `notify_wa_copy()` is for value-document
handlers whose authoritative email is dispatched separately (HTML receipt): it
adds a WhatsApp copy only when WA is the chosen channel.

Effective channel = `Customer.resolve_channel()` with a final WA-suppression gate
(a number that replied STOP falls back to email).
"""
import logging
from datetime import timedelta

from apps.core.models import NotificationChannel
from apps.notifications.whatsapp import normalize_number, wa_suppressed

logger = logging.getLogger(__name__)

# Events too time-sensitive to hold for quiet hours.
_URGENT_EVENTS = {"subscription.suspended", "order.payment_rejected"}


def _quiet_hours_delay(event: str) -> int:
    """Seconds to hold a non-urgent WA send if we're in quiet hours (0 = send now).

    Quiet window is WA_QUIET_START..WA_QUIET_END (whole hours, WIB / UTC+7).
    Disabled by default — set both Settings (e.g. 22 and 7) to turn it on.
    """
    if event in _URGENT_EVENTS:
        return 0
    from django.utils import timezone

    from apps.core.models import Setting
    try:
        start = int(Setting.get("WA_QUIET_START", "0"))
        end = int(Setting.get("WA_QUIET_END", "0"))
    except ValueError:
        return 0
    if start == end:
        return 0

    wib = timezone.now() + timedelta(hours=7)
    h = wib.hour + wib.minute / 60
    in_quiet = (start <= h < end) if start < end else (h >= start or h < end)
    if not in_quiet:
        return 0

    target = wib.replace(hour=end % 24, minute=0, second=0, microsecond=0)
    if target <= wib:
        target += timedelta(days=1)
    return int((target - wib).total_seconds())


def _dispatch_wa(number, wa_text, *, delivery_id, template, event):
    from apps.notifications.tasks import deliver_whatsapp

    countdown = _quiet_hours_delay(event)
    if countdown:
        deliver_whatsapp.apply_async(
            args=[number, wa_text],
            kwargs={"delivery_id": delivery_id, "template": template},
            countdown=countdown,
        )
    else:
        deliver_whatsapp.delay(number, wa_text, delivery_id=delivery_id, template=template)


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


def _resolve_wa_template(event, wa_params):
    """Return (template_dict_or_None, must_skip_wa).

    must_skip_wa is True only in strict mode when no usable template is available
    — the caller should route to email instead of sending free text.
    """
    from apps.notifications.templates_registry import get_template, template_mode

    mode = template_mode()
    if mode == "off":
        return None, False
    tpl = get_template(event)
    if tpl is not None and wa_params is not None:
        return {"name": tpl.name, "language": tpl.language, "params": list(wa_params)}, False
    if mode == "strict":
        logger.warning("WA template missing for event=%s (strict mode) — routing to email", event)
        return None, True
    return None, False  # "on" mode with no template → free text


def notify(customer, *, event, wa_text, email_subject, email_body, wa_params=None):
    """Send one notification on the customer's effective channel."""
    from apps.notifications.tasks import deliver_email

    channel = effective_channel(customer)
    if channel == NotificationChannel.WHATSAPP:
        template, skip_wa = _resolve_wa_template(event, wa_params)
        if not skip_wa:
            number = normalize_number(customer.wa_number)
            delivery = _record(
                customer, event=event, channel=channel, recipient=number,
                wa_text=wa_text, email_subject=email_subject, email_body=email_body,
            )
            _dispatch_wa(number, wa_text, delivery_id=delivery.pk, template=template, event=event)
            return delivery

    delivery = _record(
        customer, event=event, channel=NotificationChannel.EMAIL,
        recipient=customer.notify_email_address,
        email_subject=email_subject, email_body=email_body,
    )
    from apps.notifications.unsubscribe import email_footer
    deliver_email.delay(
        customer.notify_email_address, email_subject, email_body + email_footer(customer)
    )
    return delivery


def notify_wa_copy(customer, *, event, wa_text, wa_params=None):
    """Push a WhatsApp copy of a value-document notification, only when WA is chosen.

    The authoritative document is emailed by the caller (HTML receipt task).
    """
    if effective_channel(customer) != NotificationChannel.WHATSAPP:
        return None

    template, skip_wa = _resolve_wa_template(event, wa_params)
    if skip_wa:
        return None

    number = normalize_number(customer.wa_number)
    delivery = _record(customer, event=event, channel=NotificationChannel.WHATSAPP,
                       recipient=number, wa_text=wa_text)
    _dispatch_wa(number, wa_text, delivery_id=delivery.pk, template=template, event=event)
    return delivery


def notify_promo(customer, *, subject, body) -> bool:
    """Send a promotional message. Email-only (F5), opt-in only, with unsubscribe link.

    Returns True if an email was queued.
    """
    if not customer.notif_promo:
        return False
    from apps.notifications.tasks import deliver_email
    from apps.notifications.unsubscribe import email_footer

    email = customer.notify_email_address
    _record(customer, event="promo", channel=NotificationChannel.EMAIL,
            recipient=email, email_subject=subject, email_body=body)
    deliver_email.delay(email, subject, body + email_footer(customer))
    return True


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
