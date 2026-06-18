"""Subscription renewal + lifecycle service.

All money flows through wallet/services.py debit() — never direct.
Status machine: ACTIVE → GRACE → SUSPENDED → (CANCELLED, admin-only).

Renewal idempotency key: "renewal:{sub_id}:{period_end_ts}"
Ensures the same billing period is never charged twice, even if the job
runs concurrently or the TopUp-triggered reactivation races with the
scheduled job.

Setting keys:
  RENEWAL_ADVANCE_HOURS     int, default 3  — how far ahead the job looks
  SUBSCRIPTION_GRACE_DAYS   int, default 3  — days from period_end before suspension
"""
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from apps.billing.models import Order, Subscription
from apps.catalog.models import Plan
from apps.core.audit import log_action
from apps.core.models import Setting
from apps.wallet.exceptions import InsufficientBalance
from apps.wallet.models import LedgerEntry
from apps.wallet.services import debit

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _renewal_idempotency_key(sub: Subscription) -> str:
    ts = int(sub.current_period_end.timestamp())
    return f"renewal:{sub.pk}:{ts}"


def _next_period_end(sub: Subscription):
    if sub.plan.interval == Plan.Interval.MONTHLY:
        return sub.current_period_end + relativedelta(months=1)
    if sub.plan.interval == Plan.Interval.YEARLY:
        return sub.current_period_end + relativedelta(years=1)
    raise ValueError(f"Cannot renew non-recurring interval: {sub.plan.interval!r}")


# ── Core lifecycle operations ─────────────────────────────────────────────────

def renew_subscription(sub: Subscription) -> bool:
    """Charge and extend a subscription by one billing period.

    Idempotent: the Order idempotency_key ties a charge to a specific
    (sub, period_end) pair — calling twice for the same period is safe.
    Cascades provisioner.renew() to all non-revoked grants (re-activates
    SUSPENDED grants too, so a GRACE→renewed path restores access).

    Returns:
        True  — renewed successfully.
        False — InsufficientBalance; caller should move sub to GRACE.
    """
    from apps.provisioning.models import Grant
    from apps.provisioning.registry import get as get_provisioner

    idempotency_key = _renewal_idempotency_key(sub)
    next_end = _next_period_end(sub)

    # Fast path: already renewed (outside lock — lock below will re-check)
    if Order.objects.filter(idempotency_key=idempotency_key).exists():
        logger.info("renew_subscription: sub %s already renewed for this period", sub.pk)
        return True

    try:
        with transaction.atomic():
            locked_sub = Subscription.objects.select_for_update().get(pk=sub.pk)

            if locked_sub.status == Subscription.Status.CANCELLED:
                logger.info("renew_subscription: sub %s is CANCELLED — skip", sub.pk)
                return False

            # Re-check inside lock to guard against concurrent renew calls
            if Order.objects.filter(idempotency_key=idempotency_key).exists():
                return True

            order = Order.objects.create(
                customer=locked_sub.customer,
                plan=locked_sub.plan,
                amount=locked_sub.plan.price,
                status=Order.Status.PENDING,
                idempotency_key=idempotency_key,
                subscription=locked_sub,
            )

            entry = debit(
                wallet=locked_sub.customer.wallet,
                amount=locked_sub.plan.price,
                entry_type=LedgerEntry.Type.PURCHASE,
                ref=f"order:{order.public_id}",
                note=f"Renewal: {locked_sub.plan}",
            )
            order.ledger_entry = entry
            order.status = Order.Status.PAID
            order.save(update_fields=["ledger_entry", "status", "updated_at"])

            locked_sub.current_period_end = next_end
            locked_sub.status = Subscription.Status.ACTIVE
            locked_sub.save(update_fields=["current_period_end", "status", "updated_at"])

            # Cascade renew → re-activates SUSPENDED grants too
            grants = Grant.objects.filter(
                subscription=locked_sub
            ).exclude(status=Grant.Status.REVOKED)
            for grant in grants:
                provisioner = get_provisioner(grant.type)
                provisioner.renew(grant)

        log_action(
            action="subscription.renewed",
            target=sub,
            meta={"sub_id": sub.pk, "new_period_end": next_end.isoformat()},
        )
        logger.info(
            "renew_subscription: sub %s renewed → period_end=%s", sub.pk, next_end
        )
        return True

    except InsufficientBalance:
        logger.warning(
            "renew_subscription: sub %s InsufficientBalance — balance insufficient for renewal",
            sub.pk,
        )
        return False


def suspend_subscription(sub: Subscription) -> None:
    """Suspend a subscription and cascade to all non-revoked grants.

    Idempotent: already-SUSPENDED subs are a no-op.
    """
    from apps.provisioning.models import Grant
    from apps.provisioning.registry import get as get_provisioner

    with transaction.atomic():
        locked_sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        if locked_sub.status == Subscription.Status.SUSPENDED:
            return

        locked_sub.status = Subscription.Status.SUSPENDED
        locked_sub.save(update_fields=["status", "updated_at"])

        grants = Grant.objects.filter(
            subscription=locked_sub
        ).exclude(status=Grant.Status.REVOKED)
        for grant in grants:
            provisioner = get_provisioner(grant.type)
            provisioner.suspend(grant)

    log_action(
        action="subscription.suspended",
        target=sub,
        meta={"sub_id": sub.pk},
    )
    logger.info("suspend_subscription: sub %s suspended + grants cascaded", sub.pk)


# ── Batch jobs (called by Celery tasks) ──────────────────────────────────────

def process_due_renewals() -> dict:
    """Attempt renewal for all ACTIVE subscriptions due within RENEWAL_ADVANCE_HOURS.

    For subscriptions that cannot be charged (InsufficientBalance), status is
    moved to GRACE. An AuditLog entry is written for each state change.

    Returns: {"renewed": N, "graced": N, "errors": N}
    """
    advance_hours = int(Setting.get("RENEWAL_ADVANCE_HOURS", "3"))
    cutoff = timezone.now() + timedelta(hours=advance_hours)

    due_subs = (
        Subscription.objects.filter(
            status=Subscription.Status.ACTIVE,
            auto_renew=True,
            current_period_end__lte=cutoff,
        )
        .select_related("customer__wallet", "plan")
        .order_by("current_period_end")
    )

    renewed = graced = errors = 0
    for sub in due_subs.iterator():
        try:
            ok = renew_subscription(sub)
            if ok:
                renewed += 1
            else:
                # Insufficient balance → GRACE (conditional update for idempotency)
                updated = Subscription.objects.filter(
                    pk=sub.pk, status=Subscription.Status.ACTIVE
                ).update(status=Subscription.Status.GRACE, updated_at=timezone.now())
                if updated:
                    log_action(
                        action="subscription.graced",
                        target=sub,
                        meta={"sub_id": sub.pk, "reason": "insufficient_balance"},
                    )
                    graced += 1
                    logger.warning(
                        "process_due_renewals: sub %s → GRACE (insufficient balance)", sub.pk
                    )
        except Exception as exc:
            errors += 1
            logger.error("process_due_renewals: error for sub %s: %s", sub.pk, exc)

    logger.info(
        "process_due_renewals: renewed=%d graced=%d errors=%d", renewed, graced, errors
    )
    return {"renewed": renewed, "graced": graced, "errors": errors}


def process_grace_expirations() -> dict:
    """Suspend all GRACE subscriptions whose grace window has elapsed.

    Grace window = SUBSCRIPTION_GRACE_DAYS days after current_period_end.

    Returns: {"suspended": N, "errors": N}
    """
    grace_days = int(Setting.get("SUBSCRIPTION_GRACE_DAYS", "3"))
    # period_end + grace_days <= now  →  period_end <= now - grace_days
    cutoff = timezone.now() - timedelta(days=grace_days)

    expired_grace = (
        Subscription.objects.filter(
            status=Subscription.Status.GRACE,
            current_period_end__lte=cutoff,
        )
        .select_related("customer__wallet", "plan")
        .order_by("current_period_end")
    )

    suspended = errors = 0
    for sub in expired_grace.iterator():
        try:
            suspend_subscription(sub)
            suspended += 1
        except Exception as exc:
            errors += 1
            logger.error("process_grace_expirations: error for sub %s: %s", sub.pk, exc)

    logger.info(
        "process_grace_expirations: suspended=%d errors=%d", suspended, errors
    )
    return {"suspended": suspended, "errors": errors}


# ── Non-renewing subscriptions (M2) ──────────────────────────────────────────

def cancel_subscription(sub: Subscription) -> None:
    """Cancel a subscription with auto_renew=False whose billing period has elapsed.

    M2: prevents perpetual access past the paid period (revenue leak).
    Grants are suspended before the CANCELLED status is written so access
    is revoked atomically with the state change.
    Idempotent: already-CANCELLED subs are a no-op.
    """
    from apps.provisioning.models import Grant
    from apps.provisioning.registry import get as get_provisioner

    with transaction.atomic():
        locked_sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        if locked_sub.status == Subscription.Status.CANCELLED:
            return

        locked_sub.status = Subscription.Status.CANCELLED
        locked_sub.save(update_fields=["status", "updated_at"])

        grants = Grant.objects.filter(
            subscription=locked_sub
        ).exclude(status=Grant.Status.REVOKED)
        for grant in grants:
            provisioner = get_provisioner(grant.type)
            provisioner.suspend(grant)

    log_action(
        action="subscription.cancelled",
        target=sub,
        meta={"sub_id": sub.pk, "reason": "auto_renew_expired"},
    )
    logger.info(
        "cancel_subscription: sub %s cancelled (auto_renew=False, period elapsed)", sub.pk
    )


def process_expired_non_renewal_subs() -> dict:
    """Cancel all ACTIVE subscriptions with auto_renew=False past their period end.

    M2: state machine requires active ──period elapsed & auto_renew off──> cancelled.
    Without this job, access continues indefinitely after the paid period ends.

    Returns: {"cancelled": N, "errors": N}
    """
    now = timezone.now()
    expired_subs = (
        Subscription.objects.filter(
            status=Subscription.Status.ACTIVE,
            auto_renew=False,
            current_period_end__lte=now,
        )
        .select_related("plan")
        .order_by("current_period_end")
    )

    cancelled = errors = 0
    for sub in expired_subs.iterator():
        try:
            cancel_subscription(sub)
            cancelled += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "process_expired_non_renewal_subs: error for sub %s: %s", sub.pk, exc
            )

    logger.info(
        "process_expired_non_renewal_subs: cancelled=%d errors=%d", cancelled, errors
    )
    return {"cancelled": cancelled, "errors": errors}


# ── Top-up trigger (called from billing/services.py after wallet credit) ──────

def try_renew_grace_subscriptions(customer) -> None:
    """Attempt renewal for all GRACE or SUSPENDED subscriptions of a customer.

    M1: also includes SUSPENDED subs — a customer who topped up after lapsing
    past grace should have their access restored, not stay locked out.
    Called immediately after a TopUp is credited (wallet balance restored).
    If renewal succeeds the subscription returns to ACTIVE and grants are
    re-activated via the provisioner cascade inside renew_subscription().
    Errors are caught and logged; they never bubble up to the caller.
    """
    renewable_subs = list(
        Subscription.objects.filter(
            customer=customer,
            status__in=[Subscription.Status.GRACE, Subscription.Status.SUSPENDED],
            auto_renew=True,
        ).select_related("customer__wallet", "plan")
    )

    for sub in renewable_subs:
        try:
            renewed = renew_subscription(sub)
            if renewed:
                logger.info(
                    "try_renew_grace_subscriptions: sub %s (%s) → ACTIVE after top-up",
                    sub.pk, sub.status,
                )
        except Exception as exc:
            logger.error(
                "try_renew_grace_subscriptions: error renewing sub %s: %s", sub.pk, exc
            )
