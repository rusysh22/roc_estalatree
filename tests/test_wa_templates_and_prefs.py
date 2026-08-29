"""N.5 template mode + N.7 low-balance / welcome / unsubscribe / promo."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Subscription
from apps.core.models import NotificationChannel, Setting
from apps.notifications.handlers import handle_subscription_renewed
from apps.notifications.reminders import dispatch_low_balance_alerts
from apps.notifications.templates_registry import all_templates_for_submission, get_template
from apps.notifications.unsubscribe import make_token
from tests.factories import CustomerFactory, PlanFactory, ProductFactory


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import caches
    for a in ("default", "rate_limit"):
        try:
            caches[a].clear()
        except Exception:
            pass


@pytest.fixture
def wa_customer(db):
    c = CustomerFactory()
    c.wa_number = "6281234567890"
    c.wa_number_verified_at = timezone.now()
    c.notification_channel = NotificationChannel.WHATSAPP
    c.save()
    return c


@pytest.fixture
def recurring_plan(db):
    from apps.catalog.models import Plan, Product
    p = ProductFactory(type=Product.Type.RECURRING)
    return PlanFactory(product=p, price=50_000, interval=Plan.Interval.MONTHLY)


# ── N.5 template mode ──────────────────────────────────────────────────────

def test_registry_covers_key_events():
    for key in ("otp", "subscription.renewed", "reminder:h1", "expiry:d3", "grace:g1"):
        assert get_template(key) is not None
    assert len(all_templates_for_submission()) >= 10


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
def test_template_mode_off_sends_plain_text(mock_wa, wa_customer):
    Setting.objects.update_or_create(key="WA_TEMPLATE_MODE", defaults={"value": "off"})
    handle_subscription_renewed(customer_id=wa_customer.pk, sub_id=1,
                                plan_name="Pro", new_period_end="2026-09-01T00:00:00+00:00")
    assert mock_wa.delay.call_args.kwargs["template"] is None


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
def test_template_mode_on_sends_template(mock_wa, wa_customer):
    Setting.objects.update_or_create(key="WA_TEMPLATE_MODE", defaults={"value": "on"})
    handle_subscription_renewed(customer_id=wa_customer.pk, sub_id=1,
                                plan_name="Pro", new_period_end="2026-09-01T00:00:00+00:00")
    tpl = mock_wa.delay.call_args.kwargs["template"]
    assert tpl["name"] == "subscription_renewed"
    assert tpl["params"] == ["Pro", "2026-09-01"]


# ── N.7 low-balance alert ──────────────────────────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_low_balance_alert_fires(mock_email, recurring_plan):
    c = CustomerFactory()  # wallet balance 0
    Subscription.objects.create(
        customer=c, plan=recurring_plan, status=Subscription.Status.ACTIVE,
        auto_renew=True, current_period_end=timezone.now() + timedelta(days=6),
    )
    assert dispatch_low_balance_alerts()["low_balance"] == 1
    mock_email.delay.assert_called_once()
    assert "low balance" in mock_email.delay.call_args[0][1].lower()


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_low_balance_alert_skipped_when_funded(mock_email, recurring_plan):
    from apps.wallet.models import LedgerEntry
    from apps.wallet.services import credit
    c = CustomerFactory()
    credit(c.wallet, 100_000, LedgerEntry.Type.ADJUSTMENT, ref="t:lb", note="")
    Subscription.objects.create(
        customer=c, plan=recurring_plan, status=Subscription.Status.ACTIVE,
        auto_renew=True, current_period_end=timezone.now() + timedelta(days=6),
    )
    assert dispatch_low_balance_alerts()["low_balance"] == 0


# ── N.7 unsubscribe ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_unsubscribe_promo_only(client):
    c = CustomerFactory()
    c.notif_promo = True
    c.notification_channel = NotificationChannel.WHATSAPP
    c.wa_number_verified_at = timezone.now()
    c.save()

    url = reverse("notifications:unsubscribe", args=[make_token(c.pk)])
    assert client.get(url).status_code == 200
    resp = client.post(url, {"scope": "promo"})
    assert resp.status_code == 200
    c.refresh_from_db()
    assert c.notif_promo is False
    assert c.notification_channel == NotificationChannel.WHATSAPP  # untouched


@pytest.mark.django_db
def test_unsubscribe_all_switches_to_email(client):
    c = CustomerFactory()
    c.notif_promo = True
    c.notification_channel = NotificationChannel.WHATSAPP
    c.wa_number_verified_at = timezone.now()
    c.save()

    url = reverse("notifications:unsubscribe", args=[make_token(c.pk)])
    client.post(url, {"scope": "all"})
    c.refresh_from_db()
    assert c.notif_promo is False
    assert c.notification_channel == NotificationChannel.EMAIL


@pytest.mark.django_db
def test_unsubscribe_bad_token(client):
    resp = client.get(reverse("notifications:unsubscribe", args=["garbage"]))
    assert resp.status_code == 400


# ── N.7 promo broadcast (email-only, opt-in) ───────────────────────────────

@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_broadcast_promo_respects_opt_in(mock_email):
    from apps.notifications.tasks import broadcast_promo
    opted_in = CustomerFactory()
    opted_in.notif_promo = True
    opted_in.save()
    CustomerFactory()  # not opted in

    broadcast_promo("New plans!", "Check out our new plans.")
    assert mock_email.delay.call_count == 1
    body = mock_email.delay.call_args[0][2]
    assert "unsubscribe" in body.lower() or "manage notifications" in body.lower()
