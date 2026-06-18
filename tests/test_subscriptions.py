"""Tests for Phase 6 — Subscription renewal + lifecycle.

Coverage:
 1. renew_subscription success: balance debited, period extended, grants renewed
 2. renew_subscription insufficient balance: returns False, no Order created
 3. renew_subscription idempotent: same period never double-charged
 4. suspend_subscription cascades to grants + licenses
 5. suspend_subscription idempotent: second call is a no-op
 6. process_due_renewals: success path
 7. process_due_renewals: insufficient balance → GRACE
 8. process_due_renewals: auto_renew=False is skipped
 9. process_due_renewals: future renewal not yet due is skipped
10. process_grace_expirations: suspends past-grace subs
11. process_grace_expirations: in-grace subs are not suspended
12. try_renew_grace_subscriptions: called after top-up → GRACE sub becomes ACTIVE
13. renewal creates audit log entry
14. suspension creates audit log entry
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing.models import Order, Subscription
from apps.billing.subscription_service import (
    cancel_subscription,
    process_due_renewals,
    process_expired_non_renewal_subs,
    process_grace_expirations,
    renew_subscription,
    suspend_subscription,
    try_renew_grace_subscriptions,
)
from apps.core.models import AuditLog, Setting
from apps.licensing.models import License
from apps.provisioning.models import Grant
from apps.wallet.models import LedgerEntry
from apps.wallet.services import credit
from tests.factories import CustomerFactory, DeliverableFactory, PlanFactory, ProductFactory


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def customer(db):
    return CustomerFactory()


@pytest.fixture
def recurring_plan(db):
    from apps.catalog.models import Plan, Product
    product = ProductFactory(type=Product.Type.RECURRING)
    plan = PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY)
    DeliverableFactory(plan=plan, type="license_key")
    return plan


@pytest.fixture
def active_subscription(customer, recurring_plan):
    """Customer with funded wallet + active recurring subscription."""
    from apps.billing.checkout import checkout

    credit(customer.wallet, 200_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:sub:fund", note="setup")

    _, _, _ = checkout(
        customer=customer,
        plan=recurring_plan,
        checkout_key="ck:sub:001",
        callback_url="https://example.com/cb/",
        return_url="https://example.com/ret/",
    )
    return Subscription.objects.get(customer=customer, plan=recurring_plan)


# ── 1. renew_subscription success ─────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_renew_subscription_success(active_subscription, customer, recurring_plan):
    """Successful renewal: Order created, balance debited, period extended, ACTIVE."""
    original_end = active_subscription.current_period_end
    customer.wallet.refresh_from_db()
    wallet_before = customer.wallet.balance

    result = renew_subscription(active_subscription)

    assert result is True
    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.ACTIVE
    assert active_subscription.current_period_end > original_end

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == wallet_before - recurring_plan.price

    order = Order.objects.filter(
        customer=customer,
        subscription=active_subscription,
        status=Order.Status.PAID,
    ).latest("created_at")
    assert order.amount == recurring_plan.price


@pytest.mark.django_db(transaction=True)
def test_renew_subscription_insufficient_balance(active_subscription, customer):
    """No balance: returns False, sub unchanged, no Order created."""
    # Drain the wallet
    customer.wallet.refresh_from_db()
    from apps.wallet.services import debit
    if customer.wallet.balance > 0:
        debit(customer.wallet, customer.wallet.balance,
              LedgerEntry.Type.PURCHASE, ref="test:drain", note="")

    order_count_before = Order.objects.count()
    result = renew_subscription(active_subscription)

    assert result is False
    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.ACTIVE  # unchanged
    assert Order.objects.count() == order_count_before  # no new Order


@pytest.mark.django_db(transaction=True)
def test_renew_subscription_idempotent(active_subscription, customer, recurring_plan):
    """Calling renew_subscription twice for the same period charges only once."""
    customer.wallet.refresh_from_db()
    wallet_before = customer.wallet.balance

    # Snapshot idempotency key BEFORE any renewal (current_period_end unchanged)
    original_end_ts = int(active_subscription.current_period_end.timestamp())
    idempotency_key = f"renewal:{active_subscription.pk}:{original_end_ts}"

    result1 = renew_subscription(active_subscription)
    # Do NOT refresh active_subscription — keeps original current_period_end so
    # the second call computes the same idempotency key and short-circuits.
    result2 = renew_subscription(active_subscription)

    assert result1 is True
    assert result2 is True  # idempotent — returns True without re-charging

    customer.wallet.refresh_from_db()
    # Balance should only be debited ONCE
    assert customer.wallet.balance == wallet_before - recurring_plan.price

    # Exactly one Order for this renewal period
    assert Order.objects.filter(idempotency_key=idempotency_key).count() == 1


# ── 4. suspend_subscription cascades ─────────────────────────────────────────

@pytest.mark.django_db
def test_suspend_subscription_cascades(active_subscription):
    """suspend_subscription sets sub SUSPENDED and cascades to grants + licenses."""
    grant = Grant.objects.filter(subscription=active_subscription).first()
    assert grant is not None

    suspend_subscription(active_subscription)

    active_subscription.refresh_from_db()
    grant.refresh_from_db()
    license = License.objects.get(grant=grant)

    assert active_subscription.status == Subscription.Status.SUSPENDED
    assert grant.status == Grant.Status.SUSPENDED
    assert license.status == License.Status.SUSPENDED


@pytest.mark.django_db
def test_suspend_subscription_idempotent(active_subscription):
    """Calling suspend_subscription twice is a no-op on the second call."""
    suspend_subscription(active_subscription)
    suspend_subscription(active_subscription)  # should not raise

    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.SUSPENDED

    grants = Grant.objects.filter(subscription=active_subscription, status=Grant.Status.SUSPENDED)
    assert grants.exists()


# ── 6. process_due_renewals success ──────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_process_due_renewals_success(active_subscription, customer, recurring_plan):
    """process_due_renewals renews a subscription due within the advance window."""
    # Move period_end into the past to ensure it's within the advance window
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() - timedelta(hours=1)
    )
    active_subscription.refresh_from_db()

    customer.wallet.refresh_from_db()
    wallet_before = customer.wallet.balance
    result = process_due_renewals()

    assert result["renewed"] >= 1
    assert result["errors"] == 0

    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.ACTIVE
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == wallet_before - recurring_plan.price


@pytest.mark.django_db(transaction=True)
def test_process_due_renewals_moves_to_grace(active_subscription, customer):
    """process_due_renewals moves insufficient-balance subs to GRACE."""
    # Drain wallet
    from apps.wallet.services import debit
    customer.wallet.refresh_from_db()
    if customer.wallet.balance > 0:
        debit(customer.wallet, customer.wallet.balance,
              LedgerEntry.Type.PURCHASE, ref="test:drain2", note="")

    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() - timedelta(hours=1)
    )

    result = process_due_renewals()

    assert result["graced"] >= 1
    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.GRACE


@pytest.mark.django_db(transaction=True)
def test_process_due_renewals_skips_auto_renew_false(active_subscription):
    """process_due_renewals ignores subscriptions with auto_renew=False."""
    Subscription.objects.filter(pk=active_subscription.pk).update(
        auto_renew=False,
        current_period_end=timezone.now() - timedelta(hours=1),
    )

    result = process_due_renewals()

    # This sub should not appear in renewed or graced
    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.ACTIVE  # unchanged


@pytest.mark.django_db(transaction=True)
def test_process_due_renewals_skips_future_subs(active_subscription):
    """process_due_renewals ignores subs not yet within the advance window."""
    # Far future — outside 3-hour advance window
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(days=30)
    )

    result = process_due_renewals()

    assert result["renewed"] == 0
    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.ACTIVE  # unchanged


# ── 10. process_grace_expirations ────────────────────────────────────────────

@pytest.mark.django_db
def test_process_grace_expirations_suspends_expired(active_subscription):
    """GRACE sub past grace window → SUSPENDED + grants cascade."""
    Setting.objects.update_or_create(
        key="SUBSCRIPTION_GRACE_DAYS", defaults={"value": "3"}
    )
    # Move period_end to 10 days ago (well past 3-day grace)
    Subscription.objects.filter(pk=active_subscription.pk).update(
        status=Subscription.Status.GRACE,
        current_period_end=timezone.now() - timedelta(days=10),
    )

    result = process_grace_expirations()

    assert result["suspended"] >= 1
    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.SUSPENDED

    grant = Grant.objects.filter(subscription=active_subscription).first()
    grant.refresh_from_db()
    assert grant.status == Grant.Status.SUSPENDED


@pytest.mark.django_db
def test_process_grace_expirations_keeps_recent_grace(active_subscription):
    """GRACE sub within grace window is NOT suspended."""
    Setting.objects.update_or_create(
        key="SUBSCRIPTION_GRACE_DAYS", defaults={"value": "5"}
    )
    # period_end was 2 days ago — within 5-day grace
    Subscription.objects.filter(pk=active_subscription.pk).update(
        status=Subscription.Status.GRACE,
        current_period_end=timezone.now() - timedelta(days=2),
    )

    result = process_grace_expirations()

    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.GRACE  # not suspended yet


# ── 12. try_renew_grace_subscriptions (top-up trigger) ───────────────────────

@pytest.mark.django_db(transaction=True)
def test_topup_triggers_grace_renewal(active_subscription, customer, recurring_plan):
    """After a TopUp, try_renew_grace_subscriptions renews GRACE subs."""
    # Move sub to GRACE state
    Subscription.objects.filter(pk=active_subscription.pk).update(
        status=Subscription.Status.GRACE,
        current_period_end=timezone.now() - timedelta(hours=1),
    )
    # Drain wallet first so we're sure the credit makes the difference
    from apps.wallet.services import debit
    customer.wallet.refresh_from_db()
    if customer.wallet.balance > 0:
        debit(customer.wallet, customer.wallet.balance,
              LedgerEntry.Type.PURCHASE, ref="test:drain3", note="")

    # Top up enough to cover the renewal
    credit(customer.wallet, 100_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:grace:topup", note="")

    try_renew_grace_subscriptions(customer)

    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.ACTIVE

    # License should be reactivated
    grant = Grant.objects.filter(subscription=active_subscription).first()
    grant.refresh_from_db()
    assert grant.status == Grant.Status.ACTIVE

    license = License.objects.get(grant=grant)
    assert license.status == License.Status.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_topup_grace_renewal_no_double_charge_on_retry(active_subscription, customer, recurring_plan):
    """try_renew_grace_subscriptions is idempotent — second call doesn't double-charge."""
    Subscription.objects.filter(pk=active_subscription.pk).update(
        status=Subscription.Status.GRACE,
        current_period_end=timezone.now() - timedelta(hours=1),
    )
    credit(customer.wallet, 100_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:idem:topup", note="")

    customer.wallet.refresh_from_db()
    wallet_before = customer.wallet.balance

    try_renew_grace_subscriptions(customer)
    try_renew_grace_subscriptions(customer)  # second call

    customer.wallet.refresh_from_db()
    # Charged exactly once
    assert customer.wallet.balance == wallet_before - recurring_plan.price


# ── 13 + 14. Audit logs ───────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_renewal_writes_audit_log(active_subscription):
    """Successful renewal writes a 'subscription.renewed' AuditLog entry."""
    before = AuditLog.objects.filter(action="subscription.renewed").count()
    renew_subscription(active_subscription)
    after = AuditLog.objects.filter(action="subscription.renewed").count()
    assert after == before + 1


@pytest.mark.django_db
def test_suspension_writes_audit_log(active_subscription):
    """suspend_subscription writes a 'subscription.suspended' AuditLog entry."""
    before = AuditLog.objects.filter(action="subscription.suspended").count()
    suspend_subscription(active_subscription)
    after = AuditLog.objects.filter(action="subscription.suspended").count()
    assert after == before + 1


# ── Phase 6 review tests ──────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_topup_reactivates_suspended_subscription(active_subscription, customer, recurring_plan):
    """M1: SUSPENDED sub + top-up → ACTIVE (not just GRACE)."""
    # Put sub into SUSPENDED state
    suspend_subscription(active_subscription)
    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.SUSPENDED

    # Top up enough to cover renewal
    credit(customer.wallet, 200_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:m1:topup", note="")

    try_renew_grace_subscriptions(customer)

    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.ACTIVE

    grant = Grant.objects.filter(subscription=active_subscription).first()
    grant.refresh_from_db()
    assert grant.status == Grant.Status.ACTIVE

    from apps.licensing.models import License
    license = License.objects.get(grant=grant)
    assert license.status == License.Status.ACTIVE


@pytest.mark.django_db
def test_cancel_subscription_cascades_to_grants(active_subscription):
    """M2: cancel_subscription → CANCELLED + grants SUSPENDED."""
    Subscription.objects.filter(pk=active_subscription.pk).update(auto_renew=False)

    cancel_subscription(active_subscription)

    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.CANCELLED

    grant = Grant.objects.filter(subscription=active_subscription).first()
    grant.refresh_from_db()
    assert grant.status == Grant.Status.SUSPENDED

    from apps.licensing.models import License
    license = License.objects.get(grant=grant)
    assert license.status == License.Status.SUSPENDED


@pytest.mark.django_db
def test_cancel_subscription_idempotent(active_subscription):
    """M2: calling cancel_subscription twice is a no-op on the second call."""
    Subscription.objects.filter(pk=active_subscription.pk).update(auto_renew=False)
    cancel_subscription(active_subscription)
    cancel_subscription(active_subscription)  # should not raise

    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.CANCELLED


@pytest.mark.django_db
def test_process_expired_non_renewal_cancels_past_subs(active_subscription):
    """M2: process_expired_non_renewal_subs cancels ACTIVE+auto_renew=False past period."""
    Subscription.objects.filter(pk=active_subscription.pk).update(
        auto_renew=False,
        current_period_end=timezone.now() - timedelta(days=1),
    )

    result = process_expired_non_renewal_subs()

    assert result["cancelled"] >= 1
    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.CANCELLED


@pytest.mark.django_db
def test_process_expired_non_renewal_skips_future_subs(active_subscription):
    """M2: subs with future period_end are not cancelled."""
    Subscription.objects.filter(pk=active_subscription.pk).update(
        auto_renew=False,
        current_period_end=timezone.now() + timedelta(days=15),
    )

    result = process_expired_non_renewal_subs()

    active_subscription.refresh_from_db()
    assert active_subscription.status == Subscription.Status.ACTIVE  # untouched


@pytest.mark.django_db
def test_cancel_writes_audit_log(active_subscription):
    """M2: cancel_subscription writes a 'subscription.cancelled' AuditLog entry."""
    Subscription.objects.filter(pk=active_subscription.pk).update(auto_renew=False)
    before = AuditLog.objects.filter(action="subscription.cancelled").count()
    cancel_subscription(active_subscription)
    after = AuditLog.objects.filter(action="subscription.cancelled").count()
    assert after == before + 1
