"""Tests for Phase 8 — Customer Dashboard.

Strategy: use Django test client with a logged-in user.
HTMX endpoints tested by passing the HX-Request header.
Money flows use wallet/services.py directly (not via view).

Coverage:
  1. All pages return 200 when authenticated
  2. Unauthenticated requests redirect to login
  3. Wallet ledger partial returns rows (HTMX)
  4. Toggle auto-renew flips the flag; HTMX returns toggle partial
  5. Deactivate device flips status; HTMX returns row partial
  6. Profile update saves WA number
  7. Refund request creates model; duplicate is rejected
  8. Home shows renewal CTA banner when shortfall > 0 and renewal < 24h
"""
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Order, Subscription
from apps.catalog.models import Plan, Product
from apps.dashboard.models import RefundRequest
from apps.licensing.models import Installation, License
from apps.provisioning.models import Deliverable, Grant
from apps.wallet.models import LedgerEntry
from apps.wallet.services import credit
from tests.factories import CustomerFactory, DeliverableFactory, PlanFactory, ProductFactory


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def customer(db):
    return CustomerFactory()


@pytest.fixture
def authed_client(customer):
    c = Client()
    c.force_login(customer.user)
    return c


@pytest.fixture
def funded_customer(customer):
    credit(customer.wallet, 500_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:dash:fund", note="setup")
    return customer


@pytest.fixture
def paid_order(funded_customer):
    product = ProductFactory(type=Product.Type.ONE_TIME)
    plan = PlanFactory(product=product, price=50_000)
    DeliverableFactory(plan=plan, type="license_key")
    from apps.billing.checkout import checkout
    credit(funded_customer.wallet, 50_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:dash:order:fund", note="")
    order, _, _ = checkout(
        customer=funded_customer,
        plan=plan,
        checkout_key="ck:dash:order:001",
        callback_url="https://x.com/cb/",
        return_url="https://x.com/ret/",
    )
    return order


@pytest.fixture
def active_subscription(funded_customer):
    product = ProductFactory(type=Product.Type.RECURRING)
    plan = PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY)
    DeliverableFactory(plan=plan, type="license_key")
    from apps.billing.checkout import checkout
    order, _, _ = checkout(
        customer=funded_customer,
        plan=plan,
        checkout_key="ck:dash:sub:001",
        callback_url="https://x.com/cb/",
        return_url="https://x.com/ret/",
    )
    return Subscription.objects.get(customer=funded_customer, plan=plan)


@pytest.fixture
def license_with_install(paid_order, funded_customer):
    license = License.objects.filter(customer=funded_customer).first()
    install = Installation.objects.create(
        license=license,
        fingerprint="abc123fingerprint",
        name="My Laptop",
        status=Installation.Status.ACTIVE,
    )
    return license, install


# ── 1. All pages return 200 when authenticated ────────────────────────────────

@pytest.mark.django_db
def test_home_returns_200(authed_client):
    assert authed_client.get(reverse("dashboard:home")).status_code == 200


@pytest.mark.django_db
def test_wallet_returns_200(authed_client):
    assert authed_client.get(reverse("dashboard:wallet")).status_code == 200


@pytest.mark.django_db
def test_products_returns_200(authed_client):
    assert authed_client.get(reverse("dashboard:products")).status_code == 200


@pytest.mark.django_db
def test_devices_returns_200(authed_client):
    assert authed_client.get(reverse("dashboard:devices")).status_code == 200


@pytest.mark.django_db
def test_subscriptions_returns_200(authed_client):
    assert authed_client.get(reverse("dashboard:subscriptions")).status_code == 200


@pytest.mark.django_db
def test_invoices_returns_200(authed_client):
    assert authed_client.get(reverse("dashboard:invoices")).status_code == 200


@pytest.mark.django_db
def test_profile_returns_200(authed_client):
    assert authed_client.get(reverse("dashboard:profile")).status_code == 200


@pytest.mark.django_db
def test_support_returns_200(authed_client):
    assert authed_client.get(reverse("dashboard:support")).status_code == 200


# ── 2. Unauthenticated requests redirect to login ─────────────────────────────

@pytest.mark.django_db
def test_home_requires_login():
    resp = Client().get(reverse("dashboard:home"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"] or "login" in resp["Location"]


@pytest.mark.django_db
def test_wallet_requires_login():
    resp = Client().get(reverse("dashboard:wallet"))
    assert resp.status_code == 302


# ── 3. Ledger partial (HTMX) ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_ledger_partial_returns_rows(authed_client, funded_customer):
    resp = authed_client.get(
        reverse("dashboard:ledger_partial"),
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert b"Rp" in resp.content


# ── 4. Auto-renew toggle ──────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_toggle_auto_renew_flips_flag(authed_client, funded_customer, active_subscription):
    assert active_subscription.auto_renew is True
    resp = authed_client.post(
        reverse("dashboard:toggle_auto_renew", args=[active_subscription.pk]),
    )
    assert resp.status_code == 302
    active_subscription.refresh_from_db()
    assert active_subscription.auto_renew is False


@pytest.mark.django_db(transaction=True)
def test_toggle_auto_renew_htmx_returns_partial(authed_client, funded_customer, active_subscription):
    resp = authed_client.post(
        reverse("dashboard:toggle_auto_renew", args=[active_subscription.pk]),
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert b"hx-post" in resp.content


# ── 5. Deactivate device ──────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_deactivate_device_sets_status(authed_client, funded_customer, license_with_install):
    _, install = license_with_install
    resp = authed_client.post(
        reverse("dashboard:deactivate_device", args=[install.pk]),
    )
    assert resp.status_code == 302
    install.refresh_from_db()
    assert install.status == Installation.Status.DEACTIVATED


@pytest.mark.django_db(transaction=True)
def test_deactivate_device_htmx_returns_row(authed_client, funded_customer, license_with_install):
    _, install = license_with_install
    resp = authed_client.post(
        reverse("dashboard:deactivate_device", args=[install.pk]),
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert b"Deactivated" in resp.content


# ── 6. Profile update ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_profile_saves_wa_number(authed_client, customer):
    resp = authed_client.post(
        reverse("dashboard:profile"),
        data={"wa_number": "081234567890"},
    )
    assert resp.status_code == 302
    customer.refresh_from_db()
    assert customer.wa_number == "081234567890"


# ── 7. Refund request ─────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_refund_request_creates_record(authed_client, funded_customer, paid_order):
    resp = authed_client.post(
        reverse("dashboard:refund_request", args=[paid_order.public_id]),
        data={"reason": "Changed my mind"},
    )
    assert resp.status_code == 302
    assert RefundRequest.objects.filter(customer=funded_customer, order=paid_order).exists()


@pytest.mark.django_db(transaction=True)
def test_refund_request_duplicate_rejected(authed_client, funded_customer, paid_order):
    RefundRequest.objects.create(customer=funded_customer, order=paid_order, reason="First")
    resp = authed_client.post(
        reverse("dashboard:refund_request", args=[paid_order.public_id]),
        data={"reason": "Again"},
    )
    assert resp.status_code == 302
    assert RefundRequest.objects.filter(customer=funded_customer, order=paid_order).count() == 1


@pytest.mark.django_db(transaction=True)
def test_refund_request_blank_reason_rerenders(authed_client, funded_customer, paid_order):
    resp = authed_client.post(
        reverse("dashboard:refund_request", args=[paid_order.public_id]),
        data={"reason": ""},
    )
    assert resp.status_code == 200  # re-renders form, not redirect


# ── 8. Home CTA banner ────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_home_shows_renewal_cta_when_shortfall_and_due_soon(funded_customer, active_subscription):
    from apps.wallet.services import debit
    funded_customer.wallet.refresh_from_db()
    bal = funded_customer.wallet.balance
    if bal > 0:
        debit(funded_customer.wallet, bal, LedgerEntry.Type.PURCHASE,
              ref="test:dash:drain", note="")

    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(hours=3)
    )

    c = Client()
    c.force_login(funded_customer.user)
    resp = c.get(reverse("dashboard:home"))
    assert resp.status_code == 200
    assert b"Top up now" in resp.content


@pytest.mark.django_db(transaction=True)
def test_home_no_cta_when_balance_sufficient(authed_client, funded_customer, active_subscription):
    Subscription.objects.filter(pk=active_subscription.pk).update(
        current_period_end=timezone.now() + timedelta(hours=3)
    )
    resp = authed_client.get(reverse("dashboard:home"))
    assert resp.status_code == 200
    assert b"Top up now" not in resp.content
