"""Tests for Phase 7 — Notifications.

Strategy: patch deliver_whatsapp and deliver_email at the task level so
no real sends happen. Verify the correct tasks are dispatched with the
right arguments after domain events fire.

Coverage:
  1. topup.paid → WA + email dispatched
  2. order.paid → WA + email dispatched (includes license key in message)
  3. subscription.renewed → WA dispatched (no email)
  4. subscription.graced → WA + email dispatched
  5. subscription.suspended → WA + email dispatched
  6. subscription.cancelled → WA dispatched (no email)
  7. Customer without wa_number → only email dispatched
  8. ConsoleBackend logs message instead of sending
  9. Number normalization: 081xxx → 6281xxx
 10. H-3 reminder dispatches for upcoming subs
 11. H-1 reminder dispatches for very-soon subs
 12. No reminder for subs outside both windows
"""
from datetime import timedelta
from unittest.mock import MagicMock, call, patch

import pytest
from django.utils import timezone

from apps.billing.models import Subscription
from apps.licensing.models import License
from apps.notifications.handlers import (
    handle_order_paid,
    handle_subscription_cancelled,
    handle_subscription_graced,
    handle_subscription_renewed,
    handle_subscription_suspended,
    handle_topup_paid,
)
from apps.notifications.reminders import dispatch_renewal_reminders
from apps.notifications.whatsapp import ConsoleBackend, normalize_number
from apps.wallet.models import LedgerEntry
from apps.wallet.services import credit
from tests.factories import CustomerFactory, DeliverableFactory, PlanFactory, ProductFactory


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def customer_with_wa(db):
    c = CustomerFactory()
    c.wa_number = "081234567890"
    c.save(update_fields=["wa_number"])
    return c


@pytest.fixture
def customer_no_wa(db):
    return CustomerFactory()  # wa_number="" by default


@pytest.fixture
def recurring_plan(db):
    from apps.catalog.models import Plan, Product
    product = ProductFactory(type=Product.Type.RECURRING)
    plan = PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY)
    DeliverableFactory(plan=plan, type="license_key")
    return plan


@pytest.fixture
def active_subscription(customer_with_wa, recurring_plan):
    from apps.billing.checkout import checkout
    credit(customer_with_wa.wallet, 200_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:notif:fund", note="setup")
    _, _, _ = checkout(
        customer=customer_with_wa,
        plan=recurring_plan,
        checkout_key="ck:notif:001",
        callback_url="https://example.com/cb/",
        return_url="https://example.com/ret/",
    )
    return Subscription.objects.get(customer=customer_with_wa, plan=recurring_plan)


# ── 1. topup.paid ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_topup_paid_dispatches_wa_and_email(mock_email, mock_wa, customer_with_wa):
    handle_topup_paid(customer_id=customer_with_wa.pk, amount=100_000, bonus=0)

    mock_wa.delay.assert_called_once()
    mock_email.delay.assert_called_once()

    wa_args = mock_wa.delay.call_args[0]
    assert wa_args[0] == normalize_number(customer_with_wa.wa_number)
    assert "100,000" in wa_args[1]

    email_args = mock_email.delay.call_args[0]
    assert email_args[0] == customer_with_wa.user.email


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_topup_paid_with_bonus_includes_bonus_text(mock_email, mock_wa, customer_with_wa):
    handle_topup_paid(customer_id=customer_with_wa.pk, amount=50_000, bonus=10_000)

    wa_msg = mock_wa.delay.call_args[0][1]
    assert "10,000" in wa_msg  # bonus mentioned


# ── 2. order.paid ─────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_order_paid_dispatches_with_license_key(mock_email, mock_wa, customer_with_wa, recurring_plan):
    """transaction=True: real commit fires on_commit, so emit() in checkout triggers the handler."""
    from apps.billing.checkout import checkout

    credit(customer_with_wa.wallet, 100_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:notif:order:fund", note="")
    order, _, _ = checkout(
        customer=customer_with_wa,
        plan=recurring_plan,
        checkout_key="ck:notif:order:001",
        callback_url="https://x.com/cb/",
        return_url="https://x.com/ret/",
    )

    # The emit() inside checkout fires handle_order_paid via on_commit (real tx)
    mock_wa.delay.assert_called_once()
    wa_msg = mock_wa.delay.call_args[0][1]
    license = License.objects.filter(customer=customer_with_wa).first()
    assert license.key in wa_msg


# ── 3. subscription.renewed → WA only ────────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_subscription_renewed_sends_wa_not_email(mock_email, mock_wa, customer_with_wa):
    handle_subscription_renewed(customer_id=customer_with_wa.pk, sub_id=1,
                                 plan_name="Pro Monthly",
                                 new_period_end="2026-07-18T00:00:00+00:00")

    mock_wa.delay.assert_called_once()
    mock_email.delay.assert_not_called()

    wa_msg = mock_wa.delay.call_args[0][1]
    assert "Diperpanjang" in wa_msg
    assert "2026-07-18" in wa_msg


# ── 4. subscription.graced → WA + email ──────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_subscription_graced_sends_wa_and_email(mock_email, mock_wa, customer_with_wa):
    handle_subscription_graced(customer_id=customer_with_wa.pk, sub_id=1,
                                plan_name="Pro Monthly", grace_days=3)

    mock_wa.delay.assert_called_once()
    mock_email.delay.assert_called_once()

    wa_msg = mock_wa.delay.call_args[0][1]
    assert "3 hari" in wa_msg


# ── 5. subscription.suspended → WA + email ───────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_subscription_suspended_sends_wa_and_email(mock_email, mock_wa, customer_with_wa):
    handle_subscription_suspended(customer_id=customer_with_wa.pk, sub_id=1,
                                   plan_name="Pro Monthly")

    mock_wa.delay.assert_called_once()
    mock_email.delay.assert_called_once()

    wa_msg = mock_wa.delay.call_args[0][1]
    assert "Ditangguhkan" in wa_msg


# ── 6. subscription.cancelled → WA only ──────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_subscription_cancelled_sends_wa_not_email(mock_email, mock_wa, customer_with_wa):
    handle_subscription_cancelled(customer_id=customer_with_wa.pk, sub_id=1,
                                   plan_name="Pro Monthly")

    mock_wa.delay.assert_called_once()
    mock_email.delay.assert_not_called()


# ── 7. No WA number → email only ─────────────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_no_wa_number_sends_email_only(mock_email, mock_wa, customer_no_wa):
    handle_topup_paid(customer_id=customer_no_wa.pk, amount=50_000, bonus=0)

    mock_wa.delay.assert_not_called()
    mock_email.delay.assert_called_once()


# ── 8. ConsoleBackend logs ────────────────────────────────────────────────────

def test_console_backend_logs_message(caplog):
    import logging
    backend = ConsoleBackend()
    with caplog.at_level(logging.INFO, logger="apps.notifications.whatsapp"):
        backend.send("628123456789", "Hello test")
    assert "628123456789" in caplog.text
    assert "Hello test" in caplog.text


# ── 9. Number normalization ───────────────────────────────────────────────────

def test_normalize_number_strips_leading_zero():
    assert normalize_number("081234567890") == "6281234567890"


def test_normalize_number_strips_plus():
    assert normalize_number("+6281234567890") == "6281234567890"


def test_normalize_number_already_normalized():
    assert normalize_number("6281234567890") == "6281234567890"


# ── 10 + 11. Renewal reminders ────────────────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_h3_reminder_dispatches_for_upcoming_sub(mock_email, mock_wa, active_subscription, customer_with_wa):
    # Move period_end to ~3h from now (within H-3 window)
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(hours=3)
    )

    result = dispatch_renewal_reminders()

    assert result["h3"] >= 1
    mock_email.delay.assert_called()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_h1_reminder_dispatches_for_very_soon_sub(mock_email, mock_wa, active_subscription, customer_with_wa):
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(hours=1)
    )

    result = dispatch_renewal_reminders()

    assert result["h1"] >= 1
    mock_email.delay.assert_called()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_no_reminder_for_distant_subs(mock_email, mock_wa, active_subscription):
    # 30 days out — outside both windows
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(days=30)
    )

    result = dispatch_renewal_reminders()

    assert result["h3"] == 0
    assert result["h1"] == 0
    mock_wa.delay.assert_not_called()
    mock_email.delay.assert_not_called()
