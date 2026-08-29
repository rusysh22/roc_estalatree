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
    """Has a WA number but channel stays EMAIL (default) — the common case."""
    c = CustomerFactory()
    c.wa_number = "081234567890"
    c.save(update_fields=["wa_number"])
    return c


@pytest.fixture
def customer_wa_channel(db):
    """Verified WA number AND channel=whatsapp — notifications resolve to WA."""
    from django.utils import timezone as _tz
    from apps.core.models import NotificationChannel

    c = CustomerFactory()
    c.wa_number = "081234567890"
    c.wa_number_verified_at = _tz.now()
    c.notification_channel = NotificationChannel.WHATSAPP
    c.save(update_fields=["wa_number", "wa_number_verified_at", "notification_channel"])
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
@patch("apps.notifications.tasks.deliver_topup_confirmation_email")
def test_topup_paid_emails_receipt_email_channel(mock_email, mock_wa, customer_with_wa):
    """Email channel: HTML receipt emailed, no WA copy."""
    handle_topup_paid(customer_id=customer_with_wa.pk, amount=100_000, bonus=0)

    mock_email.delay.assert_called_once()
    assert mock_email.delay.call_args[0][0] == customer_with_wa.user.email
    mock_wa.delay.assert_not_called()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_topup_confirmation_email")
def test_topup_paid_wa_channel_emails_receipt_and_wa_copy(mock_email, mock_wa, customer_wa_channel):
    """WA channel: receipt still emailed (always_email), plus a WA copy."""
    handle_topup_paid(customer_id=customer_wa_channel.pk, amount=50_000, bonus=10_000)

    mock_email.delay.assert_called_once()
    mock_wa.delay.assert_called_once()
    wa_args = mock_wa.delay.call_args[0]
    assert wa_args[0] == normalize_number(customer_wa_channel.wa_number)
    assert "10,000" in wa_args[1]  # bonus mentioned


# ── 2. order.paid ─────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_order_confirmation_email")
def test_order_paid_wa_channel_includes_license_key_in_wa_copy(
    mock_email, mock_wa, customer_wa_channel, recurring_plan
):
    """transaction=True: real commit fires on_commit, so emit() in checkout triggers the handler."""
    from apps.billing.checkout import checkout

    credit(customer_wa_channel.wallet, 100_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:notif:order:fund", note="")
    order, _, _ = checkout(
        customer=customer_wa_channel,
        plan=recurring_plan,
        checkout_key="ck:notif:order:001",
        callback_url="https://x.com/cb/",
        return_url="https://x.com/ret/",
    )

    mock_email.delay.assert_called_once()  # HTML receipt always emailed
    mock_wa.delay.assert_called_once()
    wa_msg = mock_wa.delay.call_args[0][1]
    license = License.objects.filter(customer=customer_wa_channel).first()
    assert license.key in wa_msg


@pytest.mark.django_db(transaction=True)
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_order_confirmation_email")
def test_order_paid_dispatches_html_confirmation_email(mock_email, mock_wa, customer_with_wa, recurring_plan):
    from apps.billing.checkout import checkout

    credit(customer_with_wa.wallet, 100_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:notif:order:fund2", note="")
    order, _, _ = checkout(
        customer=customer_with_wa,
        plan=recurring_plan,
        checkout_key="ck:notif:order:002",
        callback_url="https://x.com/cb/",
        return_url="https://x.com/ret/",
    )

    mock_email.delay.assert_called_once_with(customer_with_wa.user.email, order.pk)


# ── 3. subscription.* → single chosen channel ───────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_subscription_renewed_email_channel(mock_email, mock_wa, customer_with_wa):
    handle_subscription_renewed(customer_id=customer_with_wa.pk, sub_id=1,
                                 plan_name="Pro Monthly",
                                 new_period_end="2026-07-18T00:00:00+00:00")

    mock_email.delay.assert_called_once()
    mock_wa.delay.assert_not_called()
    body = mock_email.delay.call_args[0][2]
    assert "Diperpanjang" in body
    assert "2026-07-18" in body


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_subscription_renewed_wa_channel(mock_email, mock_wa, customer_wa_channel):
    handle_subscription_renewed(customer_id=customer_wa_channel.pk, sub_id=1,
                                 plan_name="Pro Monthly",
                                 new_period_end="2026-07-18T00:00:00+00:00")

    mock_wa.delay.assert_called_once()
    mock_email.delay.assert_not_called()
    assert "Diperpanjang" in mock_wa.delay.call_args[0][1]


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_subscription_graced_single_channel(mock_email, mock_wa, customer_with_wa, customer_wa_channel):
    handle_subscription_graced(customer_id=customer_with_wa.pk, sub_id=1,
                                plan_name="Pro Monthly", grace_days=3)
    handle_subscription_graced(customer_id=customer_wa_channel.pk, sub_id=2,
                                plan_name="Pro Monthly", grace_days=3)

    mock_email.delay.assert_called_once()   # email-channel customer
    mock_wa.delay.assert_called_once()      # wa-channel customer
    assert "3 hari" in mock_wa.delay.call_args[0][1]


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_subscription_suspended_single_channel(mock_email, mock_wa, customer_wa_channel):
    handle_subscription_suspended(customer_id=customer_wa_channel.pk, sub_id=1,
                                   plan_name="Pro Monthly")

    mock_wa.delay.assert_called_once()
    mock_email.delay.assert_not_called()
    assert "Ditangguhkan" in mock_wa.delay.call_args[0][1]


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_subscription_cancelled_email_channel(mock_email, mock_wa, customer_with_wa):
    handle_subscription_cancelled(customer_id=customer_with_wa.pk, sub_id=1,
                                   plan_name="Pro Monthly")

    mock_email.delay.assert_called_once()
    mock_wa.delay.assert_not_called()


# ── 7. No WA number → email only ─────────────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_topup_confirmation_email")
def test_no_wa_number_sends_email_only(mock_email, mock_wa, customer_no_wa):
    handle_topup_paid(customer_id=customer_no_wa.pk, amount=50_000, bonus=0)

    mock_wa.delay.assert_not_called()
    mock_email.delay.assert_called_once()


# ── 7b. HTML email rendering (real send via locmem backend, no mocking) ─────────

@pytest.mark.django_db(transaction=True)
def test_order_confirmation_email_renders_and_sends(customer_with_wa, recurring_plan):
    from django.conf import settings
    from django.core import mail
    from apps.billing.checkout import checkout
    from apps.notifications.tasks import deliver_order_confirmation_email

    credit(customer_with_wa.wallet, 100_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:notif:order:fund3", note="")
    order, _, _ = checkout(
        customer=customer_with_wa,
        plan=recurring_plan,
        checkout_key="ck:notif:order:003",
        callback_url="https://x.com/cb/",
        return_url="https://x.com/ret/",
    )

    deliver_order_confirmation_email(customer_with_wa.user.email, order.pk)

    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == [customer_with_wa.user.email]
    license = License.objects.filter(customer=customer_with_wa).first()
    html_body = sent.alternatives[0][0]
    assert license.key in html_body
    # Guards against the real production bug: Site(pk=1).domain stuck on the
    # django.contrib.sites default — this checks our own site_domain setting,
    # not the test factory's incidental @example.com buyer address.
    assert settings.SITE_DOMAIN != "example.com"
    assert f">{settings.SITE_DOMAIN}<" in html_body or settings.SITE_DOMAIN in html_body

    # PDF invoice attached
    assert len(sent.attachments) == 1
    filename, content, mimetype = sent.attachments[0]
    assert filename == f"invoice-{order.public_id}.pdf"
    assert mimetype == "application/pdf"
    assert content[:4] == b"%PDF"


@pytest.mark.django_db
def test_topup_confirmation_email_renders_and_sends(customer_with_wa):
    from django.core import mail
    from apps.notifications.tasks import deliver_topup_confirmation_email

    deliver_topup_confirmation_email(customer_with_wa.user.email, 100_000, bonus=10_000)

    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    html_body = sent.alternatives[0][0]
    assert "100.000" in html_body
    assert "10.000" in html_body
    assert "example.com" not in html_body


# ── 7c. Suppressed addresses never get emailed ──────────────────────────────────

@pytest.mark.django_db
def test_suppressed_email_is_not_sent(customer_with_wa):
    from django.core import mail
    from apps.notifications.models import EmailSuppression
    from apps.notifications.tasks import deliver_email, deliver_topup_confirmation_email

    EmailSuppression.objects.create(
        email=customer_with_wa.user.email, reason=EmailSuppression.Reason.HARD_BOUNCE,
    )

    deliver_email(customer_with_wa.user.email, "Subject", "Body")
    deliver_topup_confirmation_email(customer_with_wa.user.email, 50_000)

    assert len(mail.outbox) == 0


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


# ── 10 + 11 + 12. Renewal reminders ──────────────────────────────────────────

def _drain_wallet(customer):
    """Drain wallet to 0 so shortfall > 0 (reminders only fire on shortfall)."""
    from apps.wallet.models import LedgerEntry
    from apps.wallet.services import debit
    customer.wallet.refresh_from_db()
    bal = customer.wallet.balance
    if bal > 0:
        debit(customer.wallet, bal, LedgerEntry.Type.PURCHASE,
              ref="test:drain:reminders", note="")


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_h3_reminder_dispatches_for_upcoming_sub(mock_email, mock_wa, active_subscription, customer_with_wa):
    _drain_wallet(customer_with_wa)
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
    _drain_wallet(customer_with_wa)
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(hours=1)
    )

    result = dispatch_renewal_reminders()

    assert result["h1"] >= 1
    mock_email.delay.assert_called()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_no_reminder_when_balance_sufficient(mock_email, mock_wa, active_subscription):
    # Balance (150_000) > plan price (50_000) — M2: no reminder needed
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(hours=3)
    )

    result = dispatch_renewal_reminders()

    assert result["h3"] == 0
    mock_wa.delay.assert_not_called()
    mock_email.delay.assert_not_called()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_no_reminder_for_distant_subs(mock_email, mock_wa, active_subscription, customer_with_wa):
    _drain_wallet(customer_with_wa)
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(days=30)
    )

    result = dispatch_renewal_reminders()

    assert result["h3"] == 0
    assert result["h1"] == 0
    mock_wa.delay.assert_not_called()
    mock_email.delay.assert_not_called()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
@patch("apps.notifications.tasks.deliver_email")
def test_reminder_dedup_prevents_double_send(mock_email, mock_wa, active_subscription, customer_with_wa):
    """Calling dispatch_renewal_reminders twice for the same window must not double-send."""
    _drain_wallet(customer_with_wa)
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(hours=3)
    )

    dispatch_renewal_reminders()
    dispatch_renewal_reminders()

    # Email sent exactly once despite two runs
    assert mock_email.delay.call_count == 1
