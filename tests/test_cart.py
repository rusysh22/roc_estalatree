"""Tests for the multi-seller shopping cart (docs/feedback item #12).

Coverage:
  1. Anonymous visitor can add to a session-bound cart and view it.
  2. Guest cart merges into the customer cart on login.
  3. PWYW plans and plans with required questions can't be added to cart.
  4. Cart checkout requires login.
  5. Checkout POST with sufficient wallet balance pays every line immediately,
     across multiple sellers, and clears the cart.
  6. Checkout POST with a shortfall creates PENDING orders + one combined TopUp,
     redirects to the (mocked) Duitku invoice.
  7. Completing that TopUp (simulated webhook) finishes every pending order.
  8. order_pending routes a cart-linked TopUp to the cart receipt page.
"""
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from allauth.account.models import EmailAddress

from apps.accounts.models import SellerProfile
from apps.billing.models import Cart, CartCheckout, Order, TopUp
from apps.billing.services import _apply_topup_success
from apps.catalog.models import Product, Plan
from apps.wallet.models import LedgerEntry
from apps.wallet.services import credit
from tests.factories import CustomerFactory, PlanFactory, ProductFactory, UserFactory


@pytest.fixture
def verified_customer(db):
    c = CustomerFactory()
    EmailAddress.objects.create(user=c.user, email=c.user.email, primary=True, verified=True)
    return c


@pytest.fixture
def seller_a(db):
    return SellerProfile.objects.create(name="Seller A", slug="cart-seller-a", is_approved=True)


@pytest.fixture
def seller_b(db):
    return SellerProfile.objects.create(name="Seller B", slug="cart-seller-b", is_approved=True)


@pytest.fixture
def plan_a(seller_a):
    product = ProductFactory(seller=seller_a, visibility=Product.Visibility.PUBLIC)
    return PlanFactory(product=product, price=50_000)


@pytest.fixture
def plan_b(seller_b):
    product = ProductFactory(seller=seller_b, visibility=Product.Visibility.PUBLIC)
    return PlanFactory(product=product, price=30_000)


# ── 1. Anonymous cart ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_anonymous_can_add_and_view_cart(plan_a):
    client = Client()
    resp = client.post(reverse("storefront:cart_add", args=[plan_a.pk]))
    assert resp.status_code == 302

    resp = client.get(reverse("storefront:cart"))
    assert resp.status_code == 200
    assert plan_a.product.name.encode() in resp.content

    cart = Cart.objects.get(customer__isnull=True)
    assert cart.items.count() == 1


# ── 2. Merge on login ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_guest_cart_merges_into_customer_cart_on_login(plan_a, verified_customer):
    client = Client()
    client.post(reverse("storefront:cart_add", args=[plan_a.pk]))
    guest_cart = Cart.objects.get(customer__isnull=True)
    assert guest_cart.items.count() == 1

    client.force_login(verified_customer.user)
    resp = client.get(reverse("storefront:cart"))
    assert resp.status_code == 200
    assert plan_a.product.name.encode() in resp.content

    assert not Cart.objects.filter(pk=guest_cart.pk).exists()
    customer_cart = Cart.objects.get(customer=verified_customer)
    assert customer_cart.items.count() == 1


# ── 3. Not-cartable plans ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_pwyw_plan_cannot_be_added_to_cart(seller_a):
    product = ProductFactory(seller=seller_a, visibility=Product.Visibility.PUBLIC)
    plan = PlanFactory(product=product, price=0, pwyw=True, min_price=10_000)
    client = Client()
    resp = client.post(reverse("storefront:cart_add", args=[plan.pk]))
    assert resp.status_code == 302
    assert Cart.objects.filter(customer__isnull=True).count() == 0 or \
        not Cart.objects.get(customer__isnull=True).items.exists()


@pytest.mark.django_db
def test_plan_with_required_questions_cannot_be_added_to_cart(seller_a):
    from apps.catalog.models import ProductQuestion

    product = ProductFactory(seller=seller_a, visibility=Product.Visibility.PUBLIC)
    ProductQuestion.objects.create(product=product, label="Discord username", required=True)
    plan = PlanFactory(product=product, price=50_000)

    client = Client()
    resp = client.post(reverse("storefront:cart_add", args=[plan.pk]))
    assert resp.status_code == 302
    cart = Cart.objects.filter(customer__isnull=True).first()
    assert not cart or not cart.items.exists()


# ── 4. Checkout requires login ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_cart_checkout_requires_login(plan_a):
    client = Client()
    client.post(reverse("storefront:cart_add", args=[plan_a.pk]))
    resp = client.get(reverse("storefront:cart_checkout"))
    assert resp.status_code == 302
    assert "login" in resp["Location"]


# ── 5. Sufficient balance — multi-seller, immediate PAID ────────────────────────

@pytest.mark.django_db(transaction=True)
def test_checkout_sufficient_balance_pays_all_lines_across_sellers(verified_customer, plan_a, plan_b):
    credit(verified_customer.wallet, 100_000, LedgerEntry.Type.ADJUSTMENT, ref="test:cart:fund", note="")

    client = Client()
    client.force_login(verified_customer.user)
    client.post(reverse("storefront:cart_add", args=[plan_a.pk]))
    client.post(reverse("storefront:cart_add", args=[plan_b.pk]))

    resp = client.post(reverse("storefront:cart_checkout"))
    assert resp.status_code == 302
    assert "/cart/checkout/cco_" in resp["Location"]

    receipt = client.get(resp["Location"])
    assert receipt.status_code == 200
    assert b"Payment complete" in receipt.content

    orders = Order.objects.filter(customer=verified_customer)
    assert orders.count() == 2
    assert all(o.status == Order.Status.PAID for o in orders)
    assert {o.amount for o in orders} == {50_000, 30_000}

    from apps.billing.models import SellerEarning
    assert SellerEarning.objects.filter(order__in=orders).count() == 2

    cart = Cart.objects.get(customer=verified_customer)
    assert cart.items.count() == 0


# ── 6+7. Shortfall — combined TopUp, then webhook completes both orders ────────

@pytest.mark.django_db(transaction=True)
def test_checkout_shortfall_creates_pending_orders_and_combined_topup(verified_customer, plan_a, plan_b):
    client = Client()
    client.force_login(verified_customer.user)
    client.post(reverse("storefront:cart_add", args=[plan_a.pk]))
    client.post(reverse("storefront:cart_add", args=[plan_b.pk]))

    mock_result = MagicMock()
    mock_result.reference = "REF999"
    mock_result.payment_url = "https://sandbox.duitku.com/pay/REF999"
    mock_client = MagicMock()
    mock_client.create_invoice.return_value = mock_result

    with patch("apps.billing.duitku.DuitkuClient.from_settings", return_value=mock_client):
        resp = client.post(reverse("storefront:cart_checkout"), {"payment_method": "VC"})

    assert resp.status_code == 302
    assert resp["Location"] == "https://sandbox.duitku.com/pay/REF999"

    orders = Order.objects.filter(customer=verified_customer)
    assert orders.count() == 2
    assert all(o.status == Order.Status.PENDING for o in orders)

    topup = TopUp.objects.get(customer=verified_customer)
    assert topup.amount == 80_000  # 50,000 + 30,000, no existing balance
    assert topup.cart_checkout is not None
    assert topup.cart_checkout.status == CartCheckout.Status.PENDING

    # Cart is cleared even though orders are still pending (they're tracked via cart_checkout)
    assert Cart.objects.get(customer=verified_customer).items.count() == 0

    # Simulate the webhook confirming payment
    applied = _apply_topup_success(topup)
    assert applied is True

    for order in orders:
        order.refresh_from_db()
        assert order.status == Order.Status.PAID

    topup.cart_checkout.refresh_from_db()
    assert topup.cart_checkout.status == CartCheckout.Status.COMPLETED


# ── 8. order_pending routes cart-linked topups to the cart receipt ──────────────

@pytest.mark.django_db
def test_order_pending_redirects_to_cart_receipt_for_cart_topup(verified_customer):
    cart_checkout = CartCheckout.objects.create(customer=verified_customer)
    topup = TopUp.objects.create(customer=verified_customer, amount=10_000, cart_checkout=cart_checkout)

    client = Client()
    client.force_login(verified_customer.user)
    resp = client.get(f"{reverse('storefront:order_pending')}?merchantOrderId={topup.public_id}")

    assert resp.status_code == 302
    assert resp["Location"] == reverse("storefront:cart_checkout_receipt", args=[cart_checkout.public_id])
