"""Tests for Phase 9 — Public Storefront.

Coverage:
  1. Marketplace landing page (/): 200, shows trending products/sellers
  2. Individual seller store page (/<slug>/): 200 when published, 404 for unknown slug
  3. Product detail: 200 for public product, 404 for draft
  4. Checkout GET: 200 when logged in; 302 to login when anon
  5. Checkout POST: balance sufficient → PAID order → redirect to order_status
  6. Checkout POST: balance insufficient → Sumopod redirect (mocked)
  7. Order status: PAID renders success; PENDING renders pending
  8. Top-up GET: 200 when logged in
  9. Top-up POST: valid amount → Sumopod redirect (mocked); invalid amount → re-render
 10. Contact GET: 200 for contact-type product
 11. Contact POST: creates Lead; redirects to WA if wa_number set
 12. Auto-create Customer on first checkout
"""
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import SellerProfile
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
        title="Berlanggan Store",
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
    from allauth.account.models import EmailAddress
    c = CustomerFactory()
    EmailAddress.objects.create(user=c.user, email=c.user.email, primary=True, verified=True)
    return c


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


# ── Landing page (marketplace home) ────────────────────────────────────────────

@pytest.mark.django_db
def test_landing_page_returns_200():
    resp = Client().get(reverse("storefront:page"))
    assert resp.status_code == 200
    assert b"Berlanggan" in resp.content


@pytest.mark.django_db
def test_landing_page_shows_trending_product(customer):
    seller = SellerProfile.objects.create(
        name="Acme Creator", slug="acme-creator", is_active=True, is_approved=True,
    )
    product = ProductFactory(
        visibility=Product.Visibility.PUBLIC, name="Landing Trend Product", seller=seller,
    )
    plan = PlanFactory(product=product, price=75_000, is_active=True)
    Order.objects.create(customer=customer, plan=plan, amount=plan.price, status=Order.Status.PAID)

    resp = Client().get(reverse("storefront:page"))
    assert resp.status_code == 200
    assert b"Landing Trend Product" in resp.content
    assert b"Acme Creator" in resp.content


# ── Search (docs: search bar for products/sellers) ──────────────────────────────

@pytest.mark.django_db
def test_search_no_query_shows_prompt():
    resp = Client().get(reverse("storefront:search"))
    assert resp.status_code == 200
    assert b"get started" in resp.content.lower()


@pytest.mark.django_db
def test_search_matches_product_name():
    seller = SellerProfile.objects.create(name="Acme Creator", slug="search-seller-a", is_active=True, is_approved=True)
    product = ProductFactory(visibility=Product.Visibility.PUBLIC, name="Notion Template Pack", seller=seller)
    PlanFactory(product=product, price=50_000, is_active=True)

    resp = Client().get(reverse("storefront:search"), {"q": "Notion"})
    assert resp.status_code == 200
    assert b"Notion Template Pack" in resp.content


@pytest.mark.django_db
def test_search_matches_seller_name():
    seller = SellerProfile.objects.create(name="Zephyr Studio", slug="search-seller-b", is_active=True, is_approved=True)
    product = ProductFactory(visibility=Product.Visibility.PUBLIC, name="Unrelated Product Name", seller=seller)
    PlanFactory(product=product, price=50_000, is_active=True)

    resp = Client().get(reverse("storefront:search"), {"q": "Zephyr"})
    assert resp.status_code == 200
    assert b"Unrelated Product Name" in resp.content


@pytest.mark.django_db
def test_search_excludes_draft_and_unapproved_seller_products():
    approved_seller = SellerProfile.objects.create(name="Approved Seller", slug="search-seller-c", is_active=True, is_approved=True)
    unapproved_seller = SellerProfile.objects.create(name="Pending Seller", slug="search-seller-d", is_active=True, is_approved=False)
    ProductFactory(visibility=Product.Visibility.DRAFT, name="Hidden Draft Widget", seller=approved_seller)
    ProductFactory(visibility=Product.Visibility.PUBLIC, name="Widget From Pending Seller", seller=unapproved_seller)

    resp = Client().get(reverse("storefront:search"), {"q": "Widget"})
    assert resp.status_code == 200
    assert b"Hidden Draft Widget" not in resp.content
    assert b"Widget From Pending Seller" not in resp.content


@pytest.mark.django_db
def test_search_no_results_message():
    resp = Client().get(reverse("storefront:search"), {"q": "zzz-nonexistent-zzz"})
    assert resp.status_code == 200
    assert b"No results" in resp.content


# ── 1+2. Store page (individual seller, /<slug>/) ─────────────────────────────

@pytest.mark.django_db
def test_store_page_slug_returns_200_when_published(store_page):
    resp = Client().get(reverse("storefront:store_page", args=[store_page.slug]))
    assert resp.status_code == 200
    assert b"Berlanggan Store" in resp.content


@pytest.mark.django_db
def test_store_page_404_for_unknown_slug():
    resp = Client().get("/no-such-slug/")
    assert resp.status_code == 404


# ── 3. Product detail ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_product_detail_returns_200(public_product):
    resp = Client().get(reverse("storefront:product", args=[public_product.slug]))
    assert resp.status_code == 200
    assert public_product.name.encode() in resp.content
    # harmonized layout: plans anchor, no stale payment-gateway chips
    assert b'id="plans"' in resp.content
    for stale in (b"GoPay", b"ShopeePay", b"Virtual Account"):
        assert stale not in resp.content


@pytest.mark.django_db
def test_product_detail_multi_plan_sticky_cta(db):
    product = ProductFactory(type=Product.Type.RECURRING, visibility=Product.Visibility.PUBLIC)
    PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY, name="A")
    PlanFactory(product=product, price=90_000, interval=Plan.Interval.MONTHLY, name="B", sort_order=1)
    resp = Client().get(reverse("storefront:product", args=[product.slug]))
    assert resp.status_code == 200
    assert b"Choose a plan" in resp.content        # sticky CTA for >1 plan
    assert b"Rp50.000" in resp.content              # "from cheapest"


@pytest.mark.django_db
def test_store_page_keeps_seller_theme(store_page):
    store_page.theme = {"primary_color": "#0ea5e9", "layout": "grid", "button_style": "pill"}
    store_page.save()
    resp = Client().get(reverse("storefront:store_page", args=[store_page.slug]))
    assert resp.status_code == 200
    assert b"--color-primary: #0ea5e9" in resp.content
    assert b"theme-card-shape" in resp.content


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
    assert b"Order total" in resp.content
    assert b"Payment method" in resp.content


# ── 5. Checkout POST: balance sufficient → PAID ───────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_checkout_post_sufficient_balance_creates_paid_order(funded_authed_client, funded_customer, public_product):
    plan = public_product.plans.first()
    resp = funded_authed_client.post(reverse("storefront:checkout", args=[plan.pk]))
    assert resp.status_code == 302
    assert Order.objects.filter(customer=funded_customer, status=Order.Status.PAID).exists()


@pytest.mark.django_db(transaction=True)
def test_pwyw_checkout_accepts_thousand_separated_amount(funded_authed_client, funded_customer):
    """The 'name your price' field submits a formatted string like '150.000'."""
    product = ProductFactory(visibility=Product.Visibility.PUBLIC)
    plan = PlanFactory(product=product, price=0, pwyw=True, min_price=25_000, is_active=True)
    DeliverableFactory(plan=plan, type="license_key")

    resp = funded_authed_client.post(reverse("storefront:checkout", args=[plan.pk]),
                                     {"pwyw_price": "Rp150.000"})
    assert resp.status_code == 302
    order = Order.objects.filter(customer=funded_customer, status=Order.Status.PAID).latest("created_at")
    assert order.amount == 150_000


@pytest.mark.django_db
def test_topup_accepts_thousand_separated_amount(authed_client):
    mock_client = MagicMock()
    mock_client.create_payment.return_value = MagicMock(fee=0, payment_id="R1", payment_url="https://pay.sumopod.com/pay/R1")
    with patch("apps.billing.sumopod.SumopodClient.from_settings", return_value=mock_client):
        resp = authed_client.post(reverse("storefront:topup"), {"amount": "150.000", "payment_method": "VC"})
    assert resp.status_code == 302
    from apps.billing.models import TopUp
    assert TopUp.objects.latest("created_at").amount == 150_000


# ── 6. Checkout POST: balance insufficient → Sumopod redirect ─────────────────

@pytest.mark.django_db(transaction=True)
def test_checkout_post_insufficient_balance_redirects_to_payment(authed_client, customer, public_product):
    plan = public_product.plans.first()

    mock_result = MagicMock()
    mock_result.fee = 0
    mock_result.payment_id = "REF123"
    mock_result.payment_url = "https://pay.sumopod.com/pay/REF123"

    mock_client = MagicMock()
    mock_client.create_payment.return_value = mock_result

    with patch("apps.billing.sumopod.SumopodClient.from_settings", return_value=mock_client):
        resp = authed_client.post(reverse("storefront:checkout", args=[plan.pk]), {"payment_method": "VC"})

    assert resp.status_code == 302
    assert "sumopod.com" in resp["Location"]


@pytest.mark.django_db(transaction=True)
def test_guest_checkout_creates_account_and_redirects_to_payment(public_product):
    """Regression test: the custom User model has no `username` field (email-only
    auth, see apps/accounts/models.py). Guest checkout must not try to generate/filter
    by username — that previously crashed with a 500 (FieldError) for every anonymous
    guest checkout that needed a top-up."""
    from apps.accounts.models import Customer, User

    plan = public_product.plans.first()
    guest_email = "newguest@example.com"
    assert not User.objects.filter(email=guest_email).exists()

    mock_result = MagicMock()
    mock_result.fee = 0
    mock_result.payment_id = "REF456"
    mock_result.payment_url = "https://pay.sumopod.com/pay/REF456"

    mock_client = MagicMock()
    mock_client.create_payment.return_value = mock_result

    with patch("apps.billing.sumopod.SumopodClient.from_settings", return_value=mock_client):
        resp = Client().post(reverse("storefront:checkout", args=[plan.pk]), {
            "guest_email": guest_email,
            "payment_method": "VC",
        })

    assert resp.status_code == 302
    assert "sumopod.com" in resp["Location"]
    user = User.objects.get(email=guest_email)
    assert Customer.objects.filter(user=user).exists()


# ── 7. Order status ───────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_order_status_paid_shows_success(funded_authed_client, funded_customer, public_product):
    plan = public_product.plans.first()
    funded_authed_client.post(reverse("storefront:checkout", args=[plan.pk]))
    order = Order.objects.get(customer=funded_customer, status=Order.Status.PAID)
    resp = funded_authed_client.get(reverse("storefront:order_status", args=[order.public_id]))
    assert resp.status_code == 200
    assert b"complete" in resp.content


@pytest.mark.django_db
def test_order_status_anonymous_without_token_redirects_to_login(funded_customer, public_product):
    plan = public_product.plans.first()
    order = Order.objects.create(
        customer=funded_customer, plan=plan, amount=plan.price, status=Order.Status.PAID,
        idempotency_key="ck:test:receipt:noauth",
    )
    resp = Client().get(reverse("storefront:order_status", args=[order.public_id]))
    assert resp.status_code == 302
    assert "login" in resp["Location"]


@pytest.mark.django_db
def test_order_status_anonymous_with_valid_token_shows_receipt(funded_customer, public_product):
    from apps.storefront.views import build_order_receipt_token

    plan = public_product.plans.first()
    order = Order.objects.create(
        customer=funded_customer, plan=plan, amount=plan.price, status=Order.Status.PAID,
        idempotency_key="ck:test:receipt:token",
    )
    token = build_order_receipt_token(order)
    url = reverse("storefront:order_status", args=[order.public_id])
    resp = Client().get(f"{url}?token={token}")
    assert resp.status_code == 200
    assert b"complete" in resp.content
    # enriched receipt details + invoice download
    assert b"Ordered by" in resp.content
    assert b"Download invoice (PDF)" in resp.content


@pytest.mark.django_db
def test_order_invoice_pdf_via_token(funded_customer, public_product):
    from apps.storefront.views import build_order_receipt_token

    plan = public_product.plans.first()
    order = Order.objects.create(
        customer=funded_customer, plan=plan, amount=plan.price, status=Order.Status.PAID,
        invoice_number=4242, idempotency_key="ck:test:invoice:token",
    )
    token = build_order_receipt_token(order)
    url = reverse("storefront:order_invoice_pdf", args=[order.public_id])
    resp = Client().get(f"{url}?token={token}")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert "attachment" in resp["Content-Disposition"]
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_order_invoice_pdf_owner_login(funded_authed_client, funded_customer, public_product):
    plan = public_product.plans.first()
    order = Order.objects.create(
        customer=funded_customer, plan=plan, amount=plan.price, status=Order.Status.PAID,
        idempotency_key="ck:test:invoice:owner",
    )
    resp = funded_authed_client.get(reverse("storefront:order_invoice_pdf", args=[order.public_id]))
    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_order_invoice_pdf_pending_is_404(funded_customer, public_product):
    from apps.storefront.views import build_order_receipt_token

    plan = public_product.plans.first()
    order = Order.objects.create(
        customer=funded_customer, plan=plan, amount=plan.price, status=Order.Status.PENDING,
        idempotency_key="ck:test:invoice:pending",
    )
    token = build_order_receipt_token(order)
    url = reverse("storefront:order_invoice_pdf", args=[order.public_id])
    resp = Client().get(f"{url}?token={token}")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_order_invoice_pdf_no_access_redirects(funded_customer, public_product):
    plan = public_product.plans.first()
    order = Order.objects.create(
        customer=funded_customer, plan=plan, amount=plan.price, status=Order.Status.PAID,
        idempotency_key="ck:test:invoice:noauth",
    )
    resp = Client().get(reverse("storefront:order_invoice_pdf", args=[order.public_id]))
    assert resp.status_code == 302
    assert "login" in resp["Location"]


@pytest.mark.django_db
def test_order_status_token_for_different_order_is_rejected(funded_customer, public_product):
    from apps.storefront.views import build_order_receipt_token

    plan = public_product.plans.first()
    order_a = Order.objects.create(
        customer=funded_customer, plan=plan, amount=plan.price, status=Order.Status.PAID,
        idempotency_key="ck:test:receipt:a",
    )
    order_b = Order.objects.create(
        customer=funded_customer, plan=plan, amount=plan.price, status=Order.Status.PAID,
        idempotency_key="ck:test:receipt:b",
    )
    token_for_a = build_order_receipt_token(order_a)
    url_for_b = reverse("storefront:order_status", args=[order_b.public_id])
    resp = Client().get(f"{url_for_b}?token={token_for_a}")
    # Token doesn't match this public_id, falls through to the login-required path
    assert resp.status_code == 302
    assert "login" in resp["Location"]


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
    mock_result.fee = 0
    mock_result.payment_id = "REF456"
    mock_result.payment_url = "https://pay.sumopod.com/pay/REF456"

    mock_client = MagicMock()
    mock_client.create_payment.return_value = mock_result

    with patch("apps.billing.sumopod.SumopodClient.from_settings", return_value=mock_client):
        resp = authed_client.post(reverse("storefront:topup"), {"amount": "100000", "payment_method": "VC"})

    assert resp.status_code == 302
    assert "sumopod.com" in resp["Location"]


@pytest.mark.django_db
def test_topup_post_invalid_amount_rerenders(authed_client):
    resp = authed_client.post(reverse("storefront:topup"), {"amount": "0"})
    assert resp.status_code == 200
    assert b"minimum" in resp.content.lower()


@pytest.mark.django_db
def test_topup_post_unverified_email_blocked():
    unverified_customer = CustomerFactory()
    client = Client()
    client.force_login(unverified_customer.user)
    resp = client.post(reverse("storefront:topup"), {"amount": "100000", "payment_method": "VC"})
    assert resp.status_code == 302
    assert resp["Location"] == reverse("account_email")


@pytest.mark.django_db
def test_checkout_post_unverified_email_blocked_when_payment_needed(public_product):
    """An already-logged-in (not fresh guest) buyer with an unverified email is
    blocked from a gateway-backed checkout (docs/feedback, item #4)."""
    unverified_customer = CustomerFactory()
    client = Client()
    client.force_login(unverified_customer.user)
    plan = public_product.plans.first()
    resp = client.post(reverse("storefront:checkout", args=[plan.pk]), {"payment_method": "VC"})
    assert resp.status_code == 302
    assert resp["Location"] == reverse("account_email")


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
