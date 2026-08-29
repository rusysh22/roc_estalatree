"""kirim.chat webhook handling — delivery status + inbound STOP (ADR-022).

Payload (docs.kirim.chat/developers):
    {"event_type": "message.delivered", "event_id": "uuid", "timestamp": "...",
     "data": {"message_id": "...", "customer_phone": "62...", "direction": "...",
              "content": "...", "channel": "whatsapp"}}

Signature header: `X-KirimChat-Signature: sha256=<hex>` — HMAC-SHA256 of the raw body.
"""
import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-KirimChat-Signature"

_STOP_WORDS = {"stop", "berhenti", "unsub", "unsubscribe", "batal", "keluar"}
_START_WORDS = {"mulai", "start", "lanjut", "subscribe"}

_STATUS_MAP = {
    "message.sent": "sent",
    "message.delivered": "delivered",
    "message.read": "read",
    "message.failed": "failed",
}


def verify_signature(raw_body: bytes, header_value: str, secret: str) -> bool:
    if not secret or not header_value:
        return False
    provided = header_value.strip()
    if provided.startswith("sha256="):
        provided = provided[len("sha256="):]
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def webhook_secret() -> str:
    return os.environ.get("KIRIMCHAT_WEBHOOK_SECRET", "")


def process_event(event_type: str, data: dict) -> None:
    """Route one webhook event. Idempotency is handled by the caller."""
    if event_type in _STATUS_MAP:
        _handle_status(_STATUS_MAP[event_type], data)
    elif event_type == "message.received":
        _handle_inbound(data)
    else:
        logger.info("kirimchat webhook: ignoring event_type=%s", event_type)


def _handle_status(status: str, data: dict) -> None:
    from apps.notifications.models import NotificationDelivery

    msg_id = data.get("message_id")
    if not msg_id:
        return
    delivery = (
        NotificationDelivery.objects.filter(provider_msg_id=msg_id)
        .order_by("-created_at")
        .first()
    )
    if not delivery:
        logger.info("kirimchat webhook: no delivery for message_id=%s (status=%s)", msg_id, status)
        return

    # Already handled a failure for this delivery — ignore any later status events.
    if delivery.status in (
        NotificationDelivery.Status.FAILED,
        NotificationDelivery.Status.FALLBACK_SENT,
    ):
        return

    if status == "failed":
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.error = data.get("error") or data.get("reason") or "provider reported failure"
        delivery.save(update_fields=["status", "error", "updated_at"])
        from apps.notifications.dispatch import fallback_delivery_to_email
        fallback_delivery_to_email(delivery)
        return

    # Don't regress on out-of-order sent/delivered/read events.
    rank = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}
    if rank.get(status, 0) <= rank.get(delivery.status, 0):
        return
    delivery.status = status
    delivery.save(update_fields=["status", "updated_at"])


def _handle_inbound(data: dict) -> None:
    from apps.accounts.models import Customer
    from apps.core.models import NotificationChannel
    from apps.notifications.models import WhatsAppSuppression
    from apps.notifications.tasks import deliver_whatsapp
    from apps.notifications.whatsapp import normalize_number

    number = normalize_number(data.get("customer_phone") or "")
    text = (data.get("content") or "").strip().lower()
    if not number:
        return

    if text in _START_WORDS:
        deleted, _ = WhatsAppSuppression.objects.filter(number=number).delete()
        if deleted:
            deliver_whatsapp.delay(
                number,
                "WhatsApp notifications re-enabled. Manage your preferences in your dashboard.",
            )
        return

    if text not in _STOP_WORDS:
        return

    _, created = WhatsAppSuppression.objects.get_or_create(
        number=number,
        defaults={"reason": WhatsAppSuppression.Reason.OPT_OUT, "detail": f"inbound: {text}"},
    )

    # Move any customer on this number back to email.
    Customer.objects.filter(
        wa_number__in=[number, "0" + number[2:]],
        notification_channel=NotificationChannel.WHATSAPP,
    ).update(notification_channel=NotificationChannel.EMAIL)

    if created:
        deliver_whatsapp.delay(
            number,
            "You have unsubscribed from WhatsApp notifications. "
            "Future notifications will be sent by email. "
            "Reply START to re-enable.",
        )
