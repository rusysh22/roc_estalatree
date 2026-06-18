"""Upcoming renewal reminder logic — H-3 and H-1 notifications.

Called by the send_renewal_reminders Celery task (scheduled hourly).
Reminder windows are intentionally wider than 1h so they fire even
if the task runs a few minutes late.

Phase 6 review M3: this is the missing "upcoming renewal" event source.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


def dispatch_renewal_reminders() -> dict:
    """Find subscriptions due within H-3/H-1 windows and send reminders.

    Returns {"h3": N, "h1": N} counts.
    """
    from apps.billing.models import Subscription
    from apps.notifications.tasks import deliver_email, deliver_whatsapp

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
        for sub in qs:
            try:
                customer = sub.customer
                balance = customer.wallet.balance
                shortfall = max(0, sub.plan.price - balance)

                if shortfall > 0:
                    msg = (
                        f"⏰ *Pengingat Perpanjangan ({label})*\n\n"
                        f"Langganan *{sub.plan.name}* akan diperpanjang dalam {label}.\n"
                        f"Harga: Rp{sub.plan.price:,} | Saldo: Rp{balance:,}\n"
                        f"Kekurangan: Rp{shortfall:,}\n\n"
                        f"Top up sekarang agar akses tidak terputus."
                    )
                else:
                    msg = (
                        f"⏰ *Pengingat Perpanjangan ({label})*\n\n"
                        f"Langganan *{sub.plan.name}* akan diperpanjang otomatis dalam {label}.\n"
                        f"Saldo Rp{balance:,} — cukup untuk perpanjangan."
                    )

                if customer.wa_number:
                    deliver_whatsapp.delay(customer.wa_number, msg)
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
