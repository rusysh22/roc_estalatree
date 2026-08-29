"""Notification delivery tasks (Celery).

All notification sends are async — handlers dispatch tasks, tasks do the actual sending.
Tasks retry on failure; individual send errors never crash the request path.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


def _is_suppressed(to_email: str) -> bool:
    from apps.notifications.models import EmailSuppression
    suppressed = EmailSuppression.objects.filter(email__iexact=to_email).exists()
    if suppressed:
        logger.info("email suppressed, not sending: %s", to_email)
    return suppressed


@shared_task(
    name="notifications.deliver_whatsapp",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def deliver_whatsapp(self, to_number: str, message: str, delivery_id: int | None = None):
    """Send a WA message via the configured backend.

    When `delivery_id` is given, the matching NotificationDelivery row is updated
    (sent + provider_msg_id on success; failed + email fallback once retries are
    exhausted).
    """
    from apps.notifications.whatsapp import send_whatsapp

    try:
        msg_id = send_whatsapp(to_number, message)
    except Exception as exc:
        logger.error("deliver_whatsapp: failed for %s...: %s", to_number[:6], exc)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            if delivery_id:
                _finish_wa_delivery(delivery_id, ok=False, error=str(exc))
            raise
    else:
        if delivery_id:
            _finish_wa_delivery(delivery_id, ok=True, provider_msg_id=msg_id or "")


def _finish_wa_delivery(delivery_id: int, *, ok: bool, provider_msg_id: str = "", error: str = ""):
    from apps.notifications.models import NotificationDelivery

    try:
        d = NotificationDelivery.objects.get(pk=delivery_id)
    except NotificationDelivery.DoesNotExist:
        return

    from apps.core.models import Setting
    d.provider = Setting.get("WA_BACKEND", "console")
    if ok:
        d.status = NotificationDelivery.Status.SENT
        d.provider_msg_id = provider_msg_id
        d.save(update_fields=["status", "provider", "provider_msg_id", "updated_at"])
    else:
        d.status = NotificationDelivery.Status.FAILED
        d.error = error
        d.save(update_fields=["status", "provider", "error", "updated_at"])
        from apps.notifications.dispatch import fallback_delivery_to_email
        fallback_delivery_to_email(d)


@shared_task(
    name="notifications.deliver_email",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def deliver_email(self, to_email: str, subject: str, body: str):
    """Send an email via Django's send_mail (SMTP configured in settings)."""
    from django.conf import settings
    from django.core.mail import send_mail

    if _is_suppressed(to_email):
        return

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@berlanggan.com"),
            recipient_list=[to_email],
            fail_silently=False,
        )
        logger.info("deliver_email: sent to %s — %s", to_email, subject)
    except Exception as exc:
        logger.error("deliver_email: failed for %s: %s", to_email, exc)
        raise self.retry(exc=exc)


def _site_url():
    from apps.core.branding import site_url
    return site_url()


def _base_email_context():
    from apps.core.branding import base_branding_context
    return base_branding_context()


@shared_task(
    name="notifications.deliver_order_confirmation_email",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def deliver_order_confirmation_email(self, to_email: str, order_id: int):
    """Send the HTML purchase-receipt email (license key / download / access link)."""
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.urls import reverse
    from django.utils.html import strip_tags

    if _is_suppressed(to_email):
        return

    try:
        from apps.billing.models import Order
        from apps.provisioning.models import Grant
        from apps.storefront.views import build_order_receipt_token

        order = Order.objects.select_related("plan__product", "customer__user").get(pk=order_id)
        grants = list(Grant.objects.filter(order=order))
        token = build_order_receipt_token(order)
        receipt_path = reverse("storefront:order_status", args=[order.public_id])
        context = {
            **_base_email_context(),
            "order": order,
            "grants": grants,
            "order_url": f"{_site_url()}{receipt_path}?token={token}",
        }
        html_body = render_to_string("emails/order_confirmation.html", context)
        subject = f"Purchase successful: {order.plan}"
        msg = EmailMultiAlternatives(
            subject=subject,
            body=strip_tags(html_body),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@berlanggan.com"),
            to=[to_email],
        )
        msg.attach_alternative(html_body, "text/html")

        from apps.billing.invoice_service import render_invoice_pdf
        pdf_bytes = render_invoice_pdf(order, grants)
        if pdf_bytes:
            msg.attach(f"invoice-{order.public_id}.pdf", pdf_bytes, "application/pdf")

        msg.send(fail_silently=False)
        logger.info("deliver_order_confirmation_email: sent to %s for order %s", to_email, order.public_id)
    except Exception as exc:
        logger.error("deliver_order_confirmation_email: failed for order %s: %s", order_id, exc)
        raise self.retry(exc=exc)


@shared_task(
    name="notifications.deliver_topup_confirmation_email",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def deliver_topup_confirmation_email(self, to_email: str, amount: int, bonus: int = 0, customer_id: int | None = None):
    """Send the HTML top-up receipt email."""
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.urls import reverse
    from django.utils import timezone
    from django.utils.html import strip_tags

    if _is_suppressed(to_email):
        return

    try:
        balance_after = None
        if customer_id is not None:
            from apps.accounts.models import Customer
            customer = Customer.objects.select_related("wallet").filter(pk=customer_id).first()
            if customer:
                balance_after = customer.wallet.balance

        context = {
            **_base_email_context(),
            "amount": amount,
            "bonus": bonus,
            "balance_after": balance_after,
            "now": timezone.now(),
            "wallet_url": f"{_site_url()}{reverse('dashboard:wallet')}",
        }
        html_body = render_to_string("emails/topup_confirmation.html", context)
        msg = EmailMultiAlternatives(
            subject="Top-up successful",
            body=strip_tags(html_body),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@berlanggan.com"),
            to=[to_email],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        logger.info("deliver_topup_confirmation_email: sent to %s", to_email)
    except Exception as exc:
        logger.error("deliver_topup_confirmation_email: failed for %s: %s", to_email, exc)
        raise self.retry(exc=exc)


@shared_task(
    name="notifications.send_renewal_reminders",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    acks_late=True,
)
def send_renewal_reminders(self):
    """Dispatch H-3 and H-1 renewal reminder notifications.

    H-3: subscriptions renewing in 2.5–3.5 hours.
    H-1: subscriptions renewing in 0.5–1.5 hours.
    Schedule via django-celery-beat: every hour.
    """
    from apps.notifications.reminders import dispatch_renewal_reminders

    try:
        dispatch_renewal_reminders()
    except Exception as exc:
        logger.error("send_renewal_reminders task error: %s", exc)
        raise self.retry(exc=exc)
