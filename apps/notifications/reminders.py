"""Upcoming renewal reminder logic — H-3 and H-1 notifications.

Called by the send_renewal_reminders Celery task (scheduled hourly).
Reminder windows are intentionally wider than 1h so they fire even
if the task runs a few minutes late.

M1: NotificationLog dedup prevents duplicate sends on Celery retry or
    overlapping hourly runs (unique dedup_key per sub+window+channel).
M2: Only dispatches when the customer has a shortfall — zero-cost "all good"
    reminders are suppressed.
LOW: WA number normalized before dispatch (consistent with handlers).
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

_DEDUP_KEY = "reminder:{sub_id}:{period_end}:{label}:{channel}"


def _try_log(dedup_key: str, channel: str, recipient: str) -> bool:
    """Insert a NotificationLog row. Returns True if inserted (first send), False if duplicate."""
    from apps.notifications.models import NotificationLog
    try:
        with transaction.atomic():
            NotificationLog.objects.create(
                dedup_key=dedup_key,
                channel=channel,
                recipient=recipient,
            )
        return True
    except IntegrityError:
        return False


def dispatch_renewal_reminders() -> dict:
    """Find subscriptions due within H-3/H-1 windows and send reminders.

    Only sends when the customer's balance is insufficient (shortfall > 0).
    Each send is dedup-logged so retries and overlapping runs are safe.

    Returns {"h3": N, "h1": N} counts.
    """
    from apps.billing.models import Subscription
    from apps.notifications.tasks import deliver_email, deliver_whatsapp
    from apps.notifications.whatsapp import normalize_number

    now = timezone.now()
    h3_start = now + timedelta(hours=2, minutes=30)
    h3_end = now + timedelta(hours=3, minutes=30)
    h1_start = now + timedelta(minutes=30)
    h1_end = now + timedelta(hours=1, minutes=30)

    base_qs = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        auto_renew=True,
    ).select_related("customer__user", "customer__wallet", "plan")

    h3_count = h1_count = 0

    for label, qs in (
        ("H-3", base_qs.filter(current_period_end__gte=h3_start, current_period_end__lt=h3_end)),
        ("H-1", base_qs.filter(current_period_end__gte=h1_start, current_period_end__lt=h1_end)),
    ):
        slug = label.lower().replace("-", "")  # "h3" or "h1"
        for sub in qs:
            try:
                customer = sub.customer
                balance = customer.wallet.balance
                shortfall = max(0, sub.plan.price - balance)

                # M2: only notify when action is needed (saves WA credits, reduces noise)
                if shortfall == 0:
                    continue

                period_end_date = sub.current_period_end.date().isoformat()
                msg = (
                    f"⏰ *Pengingat Perpanjangan ({label})*\n\n"
                    f"Langganan *{sub.plan.name}* akan diperpanjang dalam {label}.\n"
                    f"Harga: Rp{sub.plan.price:,} | Saldo: Rp{balance:,}\n"
                    f"Kekurangan: Rp{shortfall:,}\n\n"
                    f"Top up sekarang agar akses tidak terputus."
                )

                if customer.wa_number:
                    wa_key = _DEDUP_KEY.format(
                        sub_id=sub.pk, period_end=period_end_date,
                        label=slug, channel="wa",
                    )
                    if _try_log(wa_key, "whatsapp", normalize_number(customer.wa_number)):
                        deliver_whatsapp.delay(normalize_number(customer.wa_number), msg)

                email_key = _DEDUP_KEY.format(
                    sub_id=sub.pk, period_end=period_end_date,
                    label=slug, channel="email",
                )
                if _try_log(email_key, "email", customer.user.email):
                    deliver_email.delay(
                        customer.user.email,
                        f"Pengingat perpanjangan {label}: {sub.plan.name}",
                        msg,
                    )

                if label == "H-3":
                    h3_count += 1
                else:
                    h1_count += 1

            except Exception as exc:
                logger.error(
                    "dispatch_renewal_reminders: error for sub %s (%s): %s", sub.pk, label, exc
                )

    logger.info(
        "dispatch_renewal_reminders: h3=%d h1=%d", h3_count, h1_count
    )
    return {"h3": h3_count, "h1": h1_count}
