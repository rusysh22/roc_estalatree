"""Billing background tasks (Celery).

Safety-net task: poll Duitku for TopUps whose webhook never arrived.
Surfacing: stuck webhooks appear in the Superadmin work queue (Phase 10).
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.billing.models import TopUp

logger = logging.getLogger(__name__)

# TopUps older than this threshold without a confirmed payment are polled.
PENDING_THRESHOLD_MINUTES = 10


@shared_task(
    name="billing.poll_pending_topups",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    acks_late=True,
)
def poll_pending_topups(self):
    """Poll Duitku for every pending TopUp older than PENDING_THRESHOLD_MINUTES.

    Scheduled via django-celery-beat (every 5 minutes in prod).
    Idempotent: _apply_topup_success uses select_for_update + idempotent credit().
    """
    from apps.billing.duitku import DuitkuClient, DuitkuError
    from apps.billing.services import recheck_topup_status

    cutoff = timezone.now() - timedelta(minutes=PENDING_THRESHOLD_MINUTES)
    pending_qs = TopUp.objects.filter(
        status=TopUp.Status.PENDING,
        created_at__lt=cutoff,
    ).select_related("customer__user", "customer__wallet")

    count = pending_qs.count()
    if count == 0:
        return

    logger.info("Safety-net: checking %d stuck pending TopUps", count)

    try:
        duitku_client = DuitkuClient.from_settings()
    except DuitkuError:
        logger.warning("Duitku not configured — skipping poll_pending_topups")
        return

    resolved = 0
    for topup in pending_qs.iterator():
        try:
            recheck_topup_status(topup, duitku_client=duitku_client)
            if TopUp.objects.filter(pk=topup.pk, status=TopUp.Status.PAID).exists():
                resolved += 1
        except Exception as exc:
            logger.error("Error rechecking TopUp %s: %s", topup.public_id, exc)

    logger.info("Safety-net: resolved %d / %d pending TopUps", resolved, count)


@shared_task(
    name="billing.renew_subscriptions",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    acks_late=True,
)
def renew_subscriptions(self):
    """Renew all subscriptions due within RENEWAL_ADVANCE_HOURS.

    Subscriptions that cannot be charged (InsufficientBalance) are moved to GRACE.
    Scheduled via django-celery-beat (every hour in prod).
    Idempotent: each renewal period is guarded by Order.idempotency_key.
    """
    from apps.billing.subscription_service import process_due_renewals

    try:
        result = process_due_renewals()
        logger.info(
            "renew_subscriptions: renewed=%d graced=%d errors=%d",
            result["renewed"], result["graced"], result["errors"],
        )
    except Exception as exc:
        logger.error("renew_subscriptions task error: %s", exc)
        raise self.retry(exc=exc)


@shared_task(
    name="billing.cancel_expired_subscriptions",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    acks_late=True,
)
def cancel_expired_subscriptions(self):
    """Cancel ACTIVE subscriptions with auto_renew=False whose period has elapsed.

    M2: prevents perpetual access past the paid period (revenue leak).
    Scheduled via django-celery-beat (every 6 hours in prod, same beat as grace expiry).
    Idempotent: cancel_subscription is a conditional update.
    """
    from apps.billing.subscription_service import process_expired_non_renewal_subs

    try:
        result = process_expired_non_renewal_subs()
        logger.info(
            "cancel_expired_subscriptions: cancelled=%d errors=%d",
            result["cancelled"], result["errors"],
        )
    except Exception as exc:
        logger.error("cancel_expired_subscriptions task error: %s", exc)
        raise self.retry(exc=exc)


@shared_task(
    name="billing.expire_grace_subscriptions",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    acks_late=True,
)
def expire_grace_subscriptions(self):
    """Suspend GRACE subscriptions whose grace window has elapsed.

    Scheduled via django-celery-beat (every 6 hours in prod).
    Idempotent: suspend_subscription is a conditional update + no-op if already SUSPENDED.
    """
    from apps.billing.subscription_service import process_grace_expirations

    try:
        result = process_grace_expirations()
        logger.info(
            "expire_grace_subscriptions: suspended=%d errors=%d",
            result["suspended"], result["errors"],
        )
    except Exception as exc:
        logger.error("expire_grace_subscriptions task error: %s", exc)
        raise self.retry(exc=exc)
