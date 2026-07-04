"""Notification delivery tasks (Celery).

All notification sends are async — handlers dispatch tasks, tasks do the actual sending.
Tasks retry on failure; individual send errors never crash the request path.
"""
import base64
import logging
from functools import lru_cache

from celery import shared_task

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    """Base64 data: URI for the brand logo, inlined so email clients never need to
    fetch an external image (avoids the "logo doesn't show up" bounce — some
    clients block external images by default, and a missed collectstatic run
    would break an external URL anyway). finders.find() looks at STATICFILES_DIRS
    directly, so this works whether or not collectstatic has run.
    """
    from django.contrib.staticfiles import finders

    path = finders.find("images/brand/logo-mark-email.png")
    if not path:
        return ""
    with open(path, "rb") as f:
        data = f.read()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


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
def deliver_whatsapp(self, to_number: str, message: str):
    """Send a WA message via the configured backend (ConsoleBackend in dev, Fonnte in prod)."""
    from apps.notifications.whatsapp import send_whatsapp

    try:
        send_whatsapp(to_number, message)
    except Exception as exc:
        logger.error("deliver_whatsapp: failed for %s...: %s", to_number[:6], exc)
        raise self.retry(exc=exc)


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
    from django.conf import settings
    return f"{settings.SITE_URL_SCHEME}://{settings.SITE_DOMAIN}"


def _base_email_context():
    from django.conf import settings
    return {
        "site_name": settings.SITE_NAME,
        "site_domain": settings.SITE_DOMAIN,
        "site_url": _site_url(),
        "logo_data_uri": _logo_data_uri(),
    }


def _render_invoice_pdf(order, base_context) -> bytes | None:
    """Render the paid-invoice PDF for an order. Returns None (never raises) if
    PDF generation fails — a missing attachment shouldn't block the email itself.
    """
    import io

    from django.template.loader import render_to_string
    from xhtml2pdf import pisa

    try:
        html = render_to_string("emails/invoice_pdf.html", {**base_context, "order": order})
        buf = io.BytesIO()
        result = pisa.CreatePDF(html, dest=buf)
        if result.err:
            logger.error("_render_invoice_pdf: xhtml2pdf reported errors for order %s", order.public_id)
            return None
        return buf.getvalue()
    except Exception:
        logger.exception("_render_invoice_pdf: failed for order %s", order.public_id)
        return None


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

        pdf_bytes = _render_invoice_pdf(order, context)
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
