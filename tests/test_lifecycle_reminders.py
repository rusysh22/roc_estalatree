"""N.6 — expiry / grace-countdown / pending-order reminders."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.billing.models import Order, Subscription
from apps.notifications.reminders import (
    dispatch_expiry_reminders,
    dispatch_grace_countdown,
    dispatch_pending_order_reminders,
)
from tests.factories import CustomerFactory, PlanFactory, ProductFactory


@pytest.fixture
def recurring_plan(db):
    from apps.catalog.models import Plan, Product
    product = ProductFactory(type=Product.Type.RECURRING)
    return PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY)


def _sub(customer, plan, *, status, auto_renew, period_end):
    return Subscription.objects.create(
        customer=customer, plan=plan, status=status,
        auto_renew=auto_renew, current_period_end=period_end,
    )


# ── Expiry reminders (non-renewing) ─────────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_expiry_reminder_fires_at_d3(mock_email, recurring_plan):
    c = CustomerFactory()
    _sub(c, recurring_plan, status=Subscription.Status.ACTIVE, auto_renew=False,
         period_end=timezone.now() + timedelta(days=3))

    counts = dispatch_expiry_reminders()
    assert counts["d3"] == 1
    mock_email.delay.assert_called_once()
    assert "expiring in 3 days" in mock_email.delay.call_args[0][1].lower()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_expiry_reminder_skips_auto_renew(mock_email, recurring_plan):
    c = CustomerFactory()
    _sub(c, recurring_plan, status=Subscription.Status.ACTIVE, auto_renew=True,
         period_end=timezone.now() + timedelta(days=3))
    assert dispatch_expiry_reminders()["d3"] == 0
    mock_email.delay.assert_not_called()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_expiry_reminder_dedup(mock_email, recurring_plan):
    c = CustomerFactory()
    _sub(c, recurring_plan, status=Subscription.Status.ACTIVE, auto_renew=False,
         period_end=timezone.now() + timedelta(days=1))
    dispatch_expiry_reminders()
    dispatch_expiry_reminders()
    assert mock_email.delay.call_count == 1


# ── Grace countdown ────────────────────────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_grace_countdown_d1(mock_email, recurring_plan):
    # grace_days default 3 → suspension at period_end + 3d.
    # Want suspension ~1 day away → period_end ≈ now - 2 days.
    c = CustomerFactory()
    _sub(c, recurring_plan, status=Subscription.Status.GRACE, auto_renew=True,
         period_end=timezone.now() - timedelta(days=2))

    counts = dispatch_grace_countdown()
    assert counts["g1"] == 1
    assert "suspends in 1 day" in mock_email.delay.call_args[0][1].lower()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_grace_countdown_ignores_active(mock_email, recurring_plan):
    c = CustomerFactory()
    _sub(c, recurring_plan, status=Subscription.Status.ACTIVE, auto_renew=True,
         period_end=timezone.now() - timedelta(days=2))
    assert dispatch_grace_countdown() == {"g2": 0, "g1": 0}


# ── Pending-order nudge ────────────────────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_pending_order_nudge_at_2h(mock_email, recurring_plan):
    c = CustomerFactory()
    order = Order.objects.create(
        customer=c, plan=recurring_plan, amount=50_000,
        status=Order.Status.PENDING,
        payment_channel=Order.PaymentChannel.QRIS_STATIC,
    )
    Order.objects.filter(pk=order.pk).update(
        created_at=timezone.now() - timedelta(hours=2)
    )
    counts = dispatch_pending_order_reminders()
    assert counts["h2"] == 1
    mock_email.delay.assert_called_once()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_pending_order_nudge_skips_paid(mock_email, recurring_plan):
    c = CustomerFactory()
    order = Order.objects.create(
        customer=c, plan=recurring_plan, amount=50_000,
        status=Order.Status.PAID,
        payment_channel=Order.PaymentChannel.QRIS_STATIC,
    )
    Order.objects.filter(pk=order.pk).update(
        created_at=timezone.now() - timedelta(hours=2)
    )
    assert dispatch_pending_order_reminders()["h2"] == 0
