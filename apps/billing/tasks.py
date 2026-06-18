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
