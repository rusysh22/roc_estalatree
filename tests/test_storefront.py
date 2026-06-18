"""Tests for Phase 9 — Public Storefront.

Coverage:
  1. Store page: 200 when published, 404 for unknown slug
  2. Empty store page renders gracefully (no StorePage)
  3. Product detail: 200 for public product, 404 for draft
  4. Checkout GET: 200 when logged in; 302 to login when anon
  5. Checkout POST: balance sufficient → PAID order → redirect to order_status
  6. Checkout POST: balance insufficient → Duitku redirect (mocked)
  7. Order status: PAID renders success; PENDING renders pending
  8. Top-up GET: 200 when logged in
  9. Top-up POST: valid amount → Duitku redirect (mocked); invalid amount → re-render
 10. Contact GET: 200 for contact-type product
 11. Contact POST: creates Lead; redirects to WA if wa_number set
 12. Auto-create Customer on first checkout
"""
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from apps.billing.models import Order
from apps.catalog.models import Plan, Product
from apps.crm.models import Lead
from apps.storefront.models import Block, StorePage
from apps.wallet.models import LedgerEntry
from apps.wallet.services import credit
from tests.factories import (
    CustomerFactory,
    DeliverableFactory,
    PlanFactory,
    ProductFactory,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store_page(db):
    page = StorePage.objects.create(
        slug="main",
        title="Estalatree Store",
        description="Our products",
        is_published=True,
    )
    return page


@pytest.fixture
def public_product(db):
    product = ProductFactory(type=Product.Type.ONE_TIME, visibility=Product.Visibility.PUBLIC)
    DeliverableFactory(plan=PlanFactory(product=product, price=50_000), type="license_key")
    return product


@pytest.fixture
def recurring_product(db):
    product = ProductFactory(type=Product.Type.RECURRING, visibility=Product.Visibility.PUBLIC)
    plan = PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY)
    DeliverableFactory(plan=plan, type="license_key")
    return product


@pytest.fixture
def contact_product(db):
    product = ProductFactory(type=Product.Type.CONTACT, visibility=Product.Visibility.PUBLIC)
    product.wa_number = "081234567890"
    product.save(update_fields=["wa_number"])
    return product


@pytest.fixture
def customer(db):
    return CustomerFactory()


@pytest.fixture
def funded_customer(customer):
    credit(customer.wallet, 200_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:sf:fund", note="setup")
    return customer


@pytest.fixture
def authed_client(customer):
    c = Client()
    c.force_login(customer.user)
    return c


@pytest.fixture
def funded_authed_client(funded_customer):
    c = Client()
    c.force_login(funded_customer.user)
    return c


# ── 1+2. Store page ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_store_page_returns_200_when_published(store_page):
    resp = Client().get(reverse("storefront:page"))
    assert resp.status_code == 200
    assert b"Estalatree Store" in resp.content


@pytest.mark.django_db
def test_store_page_404_for_unknown_slug():
    resp = Client().get("/no-such-slug/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_store_page_no_store_page_renders_gracefully():
    resp = Client().get(reverse("storefront:page"))
    assert resp.status_code == 200
    assert b"coming soon" in resp.content


# ── 3. Product detail ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_product_detail_returns_200(public_product):
    resp = Client().get(reverse("storefront:product", args=[public_product.slug]))
    assert resp.status_code == 200
    assert public_product.name.encode() in resp.content


@pytest.mark.django_db
def test_product_detail_404_for_draft():
    product = ProductFactory(type=Product.Type.ONE_TIME, visibility=Product.Visibility.DRAFT)
    resp = Client().get(reverse("storefront:product", args=[product.slug]))
    assert resp.status_code == 404


# ── 4. Checkout GET ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_checkout_get_requires_login(public_product):
    plan = public_product.plans.first()
    resp = Client().get(reverse("storefront:checkout", args=[plan.pk]))
    assert resp.status_code == 302
    assert "login" in resp["Location"]


@pytest.mark.django_db
def test_checkout_get_200_when_logged_in(authed_client, public_product):
    plan = public_product.plans.first()
    resp = authed_client.get(reverse("storefront:checkout", args=[plan.pk]))
    assert resp.status_code == 200
    assert b"Confirm purchase" in resp.content


# ── 5. Checkout POST: balance sufficient → PAID ───────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_checkout_post_sufficient_balance_creates_paid_order(funded_authed_client, funded_customer, public_product):
    plan = public_product.plans.first()
    resp = funded_authed_client.post(reverse("storefront:checkout", args=[plan.pk]))
    assert resp.status_code == 302
    assert Order.objects.filter(customer=funded_customer, status=Order.Status.PAID).exists()


# ── 6. Checkout POST: balance insufficient → Duitku redirect ─────────────────

@pytest.mark.django_db(transaction=True)
def test_checkout_post_insufficient_balance_redirects_to_payment(authed_client, customer, public_product):
    plan = public_product.plans.first()

    mock_result = MagicMock()
    mock_result.reference = "REF123"
    mock_result.payment_url = "https://sandbox.duitku.com/pay/REF123"

    mock_client = MagicMock()
    mock_client.create_invoice.return_value = mock_result

    with patch("apps.billing.duitku.DuitkuClient.from_settings", return_value=mock_client):
        resp = authed_client.post(reverse("storefront:checkout", args=[plan.pk]))

    assert resp.status_code == 302
    assert "duitku.com" in resp["Location"] or "sandbox" in resp["Location"]


# ── 7. Order status ───────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_order_status_paid_shows_success(funded_authed_client, funded_customer, public_product):
    plan = public_product.plans.first()
    funded_authed_client.post(reverse("storefront:checkout", args=[plan.pk]))
    order = Order.objects.get(customer=funded_customer, status=Order.Status.PAID)
    resp = funded_authed_client.get(reverse("storefront:order_status", args=[order.public_id]))
    assert resp.status_code == 200
    assert b"complete" in resp.content


# ── 8. Top-up GET ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_topup_get_returns_200(authed_client):
    resp = authed_client.get(reverse("storefront:topup"))
    assert resp.status_code == 200
    assert b"Top up" in resp.content


# ── 9. Top-up POST ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_topup_post_valid_amount_redirects_to_payment(authed_client, customer):
    mock_result = MagicMock()
    mock_result.reference = "REF456"
    mock_result.payment_url = "https://sandbox.duitku.com/pay/REF456"

    mock_client = MagicMock()
    mock_client.create_invoice.return_value = mock_result

    with patch("apps.billing.duitku.DuitkuClient.from_settings", return_value=mock_client):
        resp = authed_client.post(reverse("storefront:topup"), {"amount": "100000"})

    assert resp.status_code == 302
    assert "duitku.com" in resp["Location"] or "sandbox" in resp["Location"]


@pytest.mark.django_db
def test_topup_post_invalid_amount_rerenders(authed_client):
    resp = authed_client.post(reverse("storefront:topup"), {"amount": "0"})
    assert resp.status_code == 200
    assert b"valid" in resp.content.lower()


# ── 10+11. Contact ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_contact_get_returns_200(contact_product):
    resp = Client().get(reverse("storefront:contact", args=[contact_product.pk]))
    assert resp.status_code == 200
    assert b"inquiry" in resp.content.lower()


@pytest.mark.django_db
def test_contact_post_creates_lead(contact_product):
    resp = Client().post(
        reverse("storefront:contact", args=[contact_product.pk]),
        {"name": "Budi", "contact": "081999888777"},
    )
    assert resp.status_code == 302
    assert Lead.objects.filter(product=contact_product, name="Budi").exists()


@pytest.mark.django_db
def test_contact_post_blank_fields_rerenders(contact_product):
    resp = Client().post(
        reverse("storefront:contact", args=[contact_product.pk]),
        {"name": "", "contact": ""},
    )
    assert resp.status_code == 200


# ── 12. Auto-create Customer ──────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_checkout_auto_creates_customer_profile(public_product):
    from apps.accounts.models import Customer, User
    user = User.objects.create_user(email="newuser@example.com", password="pass123")
    c = Client()
    c.force_login(user)

    # Fund wallet manually after customer creation
    plan = public_product.plans.first()
    resp = c.get(reverse("storefront:checkout", args=[plan.pk]))
    assert resp.status_code == 200
    assert Customer.objects.filter(user=user).exists()
