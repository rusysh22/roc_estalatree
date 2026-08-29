"""Lifecycle reminder logic — renewal, non-renewing expiry, grace countdown,
and pending-payment nudges.

Called by the `notifications.send_renewal_reminders` Celery task (scheduled
hourly). Windows are intentionally wider than 1h so a reminder still fires if
the task runs a few minutes late.

Dedup: a `NotificationLog` row per (subject, window) — a unique `dedup_key`
makes Celery retries and overlapping runs safe. Each reminder goes out on the
customer's effective channel (ADR-022), never both.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def _try_log(dedup_key: str, channel: str, recipient: str) -> bool:
    """Insert a NotificationLog row. True if inserted (first send), False if duplicate."""
    from apps.notifications.models import NotificationLog
    try:
        with transaction.atomic():
            NotificationLog.objects.create(
                dedup_key=dedup_key, channel=channel, recipient=recipient,
            )
        return True
    except IntegrityError:
        return False


def _send_once(customer, *, dedup_key: str, event: str, subject: str, body: str) -> bool:
    """Dedup-guarded single-channel reminder. Returns True if it was dispatched."""
    from apps.core.models import NotificationChannel
    from apps.notifications.dispatch import effective_channel, notify
    from apps.notifications.whatsapp import normalize_number

    channel = effective_channel(customer)
    recipient = (
        normalize_number(customer.wa_number)
        if channel == NotificationChannel.WHATSAPP
        else customer.user.email
    )
    if not _try_log(dedup_key, channel, recipient):
        return False
    notify(customer, event=event, wa_text=body, email_subject=subject, email_body=body)
    return True


def _window(now, days=0, hours=0):
    """A ±30-minute window centered `days`/`hours` from `now`."""
    center = now + timedelta(days=days, hours=hours)
    return center - timedelta(minutes=30), center + timedelta(minutes=30)


# ── Renewal reminders (auto_renew, insufficient balance) ─────────────────────

def dispatch_renewal_reminders() -> dict:
    """ACTIVE auto-renew subs due in ~3h / ~1h whose balance can't cover renewal."""
    from apps.billing.models import Subscription

    now = timezone.now()
    base_qs = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE, auto_renew=True,
    ).select_related("customer__user", "customer__wallet", "plan")

    counts = {"h3": 0, "h1": 0}
    for slug, label, (start, end) in (
        ("h3", "H-3", _window(now, hours=3)),
        ("h1", "H-1", _window(now, hours=1)),
    ):
        for sub in base_qs.filter(current_period_end__gte=start, current_period_end__lt=end):
            try:
                customer = sub.customer
                balance = customer.wallet.balance
                shortfall = max(0, sub.plan.price - balance)
                if shortfall == 0:  # only nudge when action is needed
                    continue

                pe = sub.current_period_end.date().isoformat()
                msg = (
                    f"⏰ *Renewal reminder ({label})*\n\n"
                    f"Your *{sub.plan.name}* subscription renews in {label}.\n"
                    f"Price: Rp{sub.plan.price:,} | Balance: Rp{balance:,}\n"
                    f"Shortfall: Rp{shortfall:,}\n\n"
                    f"Top up now to avoid an interruption in access."
                )
                if _send_once(
                    customer,
                    dedup_key=f"reminder:{sub.pk}:{pe}:{slug}",
                    event=f"reminder:{slug}",
                    subject=f"Renewal reminder {label}: {sub.plan.name}",
                    body=msg,
                ):
                    counts[slug] += 1
            except Exception as exc:
                logger.error("dispatch_renewal_reminders: sub %s (%s): %s", sub.pk, label, exc)

    logger.info("dispatch_renewal_reminders: %s", counts)
    return counts


# ── Expiry reminders (non-renewing subscriptions) ───────────────────────────

def dispatch_expiry_reminders() -> dict:
    """ACTIVE subs with auto_renew=False expiring in ~7d / ~3d / ~1d.

    These never renew on their own, so we remind regardless of balance.
    """
    from apps.billing.models import Subscription

    now = timezone.now()
    base_qs = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE, auto_renew=False,
    ).select_related("customer__user", "plan")

    counts = {"d7": 0, "d3": 0, "d1": 0}
    for slug, days in (("d7", 7), ("d3", 3), ("d1", 1)):
        start, end = _window(now, days=days)
        for sub in base_qs.filter(current_period_end__gte=start, current_period_end__lt=end):
            try:
                pe = sub.current_period_end.date().isoformat()
                left = "1 day" if days == 1 else f"{days} days"
                msg = (
                    f"⏳ *Access expiring in {left}*\n\n"
                    f"Your *{sub.plan.name}* access ends on {pe} and will not renew automatically.\n"
                    f"Renew from your dashboard to keep access."
                )
                if _send_once(
                    sub.customer,
                    dedup_key=f"expiry:{sub.pk}:{pe}:{slug}",
                    event=f"expiry:{slug}",
                    subject=f"Access expiring in {left}: {sub.plan.name}",
                    body=msg,
                ):
                    counts[slug] += 1
            except Exception as exc:
                logger.error("dispatch_expiry_reminders: sub %s (%s): %s", sub.pk, slug, exc)

    logger.info("dispatch_expiry_reminders: %s", counts)
    return counts


# ── Grace countdown (suspension approaching) ────────────────────────────────

def dispatch_grace_countdown() -> dict:
    """GRACE subs whose suspension (period_end + grace_days) is ~2d / ~1d away."""
    from apps.billing.models import Subscription
    from apps.core.models import Setting

    grace_days = int(Setting.get("SUBSCRIPTION_GRACE_DAYS", "3"))
    now = timezone.now()
    base_qs = Subscription.objects.filter(
        status=Subscription.Status.GRACE,
    ).select_related("customer__user", "customer__wallet", "plan")

    counts = {"g2": 0, "g1": 0}
    for slug, days_left in (("g2", 2), ("g1", 1)):
        # suspend_at = period_end + grace_days; we want suspend_at ≈ now + days_left
        # → period_end ≈ now + days_left - grace_days
        start, end = _window(now, days=days_left - grace_days)
        for sub in base_qs.filter(current_period_end__gte=start, current_period_end__lt=end):
            try:
                customer = sub.customer
                balance = customer.wallet.balance
                left = "1 day" if days_left == 1 else f"{days_left} days"
                msg = (
                    f"⚠️ *Access suspends in {left}*\n\n"
                    f"Your *{sub.plan.name}* subscription is in its grace period.\n"
                    f"Price: Rp{sub.plan.price:,} | Balance: Rp{balance:,}\n\n"
                    f"Top up now — access is suspended if it isn't renewed in time."
                )
                pe = sub.current_period_end.date().isoformat()
                if _send_once(
                    customer,
                    dedup_key=f"grace:{sub.pk}:{pe}:{slug}",
                    event=f"grace:{slug}",
                    subject=f"Access suspends in {left}: {sub.plan.name}",
                    body=msg,
                ):
                    counts[slug] += 1
            except Exception as exc:
                logger.error("dispatch_grace_countdown: sub %s (%s): %s", sub.pk, slug, exc)

    logger.info("dispatch_grace_countdown: %s", counts)
    return counts


# ── Pending-payment nudges (QRIS Statis orders) ─────────────────────────────

def dispatch_pending_order_reminders() -> dict:
    """PENDING QRIS Statis orders — nudge the buyer at ~2h and ~24h old."""
    from apps.billing.models import Order

    now = timezone.now()
    base_qs = Order.objects.filter(
        status=Order.Status.PENDING,
        payment_channel=Order.PaymentChannel.QRIS_STATIC,
    ).select_related("customer__user", "plan")

    counts = {"h2": 0, "h24": 0}
    for slug, age_hours in (("h2", 2), ("h24", 24)):
        start, end = _window(now, hours=-age_hours)  # created ~age_hours ago
        for order in base_qs.filter(created_at__gte=start, created_at__lt=end):
            try:
                msg = (
                    f"🧾 *Payment still pending*\n\n"
                    f"Your order for *{order.plan}* (Rp{order.amount:,}) is still awaiting payment.\n"
                    f"Complete the payment via the seller's QRIS, then wait for the seller to confirm."
                )
                if _send_once(
                    order.customer,
                    dedup_key=f"order_pending:{order.pk}:{slug}",
                    event=f"order_pending:{slug}",
                    subject=f"Payment still pending: {order.plan}",
                    body=msg,
                ):
                    counts[slug] += 1
            except Exception as exc:
                logger.error("dispatch_pending_order_reminders: order %s (%s): %s", order.pk, slug, exc)

    logger.info("dispatch_pending_order_reminders: %s", counts)
    return counts


# ── Combined entry point (called by the hourly task) ────────────────────────

def dispatch_all_reminders() -> dict:
    return {
        "renewal": dispatch_renewal_reminders(),
        "expiry": dispatch_expiry_reminders(),
        "grace": dispatch_grace_countdown(),
        "pending_order": dispatch_pending_order_reminders(),
    }
