"""Notification delivery tasks (Celery).

All notification sends are async — handlers dispatch tasks, tasks do the actual sending.
Tasks retry on failure; individual send errors never crash the request path.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


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

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@estalatree.com"),
            recipient_list=[to_email],
            fail_silently=False,
        )
        logger.info("deliver_email: sent to %s — %s", to_email, subject)
    except Exception as exc:
        logger.error("deliver_email: failed for %s: %s", to_email, exc)
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
