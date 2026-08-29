"""Tests for Static QRIS manual payment + Duration Plan optional discount.

Static QRIS: buyer pays the seller's own static QR directly (no wallet debit,
no Duitku). The Order stays PENDING until the seller confirms receipt, which is
what runs provisioning. No SellerEarning is recorded (money went to the seller).
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import SellerProfile
from apps.billing.checkout import (
    QrisNotAvailableError,
    checkout,
    confirm_manual_payment,
    reject_manual_payment,
)
from apps.billing.models import Order, SellerEarning, Subscription
from apps.catalog.models import Plan, Product
from apps.provisioning.models import Grant
from apps.wallet.models import LedgerEntry
from tests.factories import (
    CustomerFactory,
    DeliverableFactory,
    PlanFactory,
    ProductFactory,
    UserFactory,
)

CALLBACK_URL = "https://example.com/billing/webhook/duitku/"
RETURN_URL = "https://example.com/return/"


@pytest.fixture
def customer(db):
    return CustomerFactory()


def _png_bytes(size=(300, 300)):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()


def _qris_seller(slug="qris-seller", ready=True):
    seller = SellerProfile.objects.create(name="QRIS Seller", slug=slug, is_approved=True)
    if ready:
        seller.qris_enabled = True
        seller.qris_image = SimpleUploadedFile("qr.png", _png_bytes(), content_type="image/png")
        seller.qris_instructions = "Transfer exact amount."
        seller.save()
    return seller


@pytest.fixture
def qris_plan(db):
    seller = _qris_seller()
    product = ProductFactory(seller=seller, type=Product.Type.ONE_TIME)
    plan = PlanFactory(product=product, price=100_000, interval=Plan.Interval.NONE)
    DeliverableFactory(plan=plan, type="license_key")
    return plan


def _fund(customer, amount):
    from apps.wallet.services import credit
    credit(wallet=customer.wallet, amount=amount, entry_type=LedgerEntry.Type.ADJUSTMENT,
           ref=f"test:{customer.pk}:{amount}", note="test")
    customer.wallet.refresh_from_db()


# ── Static QRIS checkout ─────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_qris_checkout_creates_pending_order_no_debit(customer, qris_plan):
    _fund(customer, 500_000)  # plenty of balance — must NOT be used
    order, grants, payment_url = checkout(
        customer=customer, plan=qris_plan, checkout_key="ck_qris_1",
        callback_url=CALLBACK_URL, return_url=RETURN_URL, payment_method="qris_static",
    )
    assert order.status == Order.Status.PENDING
    assert order.payment_channel == Order.PaymentChannel.QRIS_STATIC
    assert order.awaiting_seller_confirmation is True
    assert grants == []
    assert payment_url is None
    assert Grant.objects.filter(order=order).count() == 0
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 500_000


@pytest.mark.django_db(transaction=True)
def test_qris_checkout_requires_ready_seller(customer, db):
    seller = _qris_seller(slug="not-ready", ready=False)
    product = ProductFactory(seller=seller, type=Product.Type.ONE_TIME)
    plan = PlanFactory(product=product, price=50_000, interval=Plan.Interval.NONE)
    DeliverableFactory(plan=plan, type="manual")
    with pytest.raises(QrisNotAvailableError):
        checkout(customer=customer, plan=plan, checkout_key="ck_qris_2",
                 callback_url=CALLBACK_URL, return_url=RETURN_URL, payment_method="qris_static")


@pytest.mark.django_db(transaction=True)
def test_confirm_manual_payment_fulfills_without_earning(customer, qris_plan):
    order, _, _ = checkout(
        customer=customer, plan=qris_plan, checkout_key="ck_qris_3",
        callback_url=CALLBACK_URL, return_url=RETURN_URL, payment_method="qris_static",
    )
    grants = confirm_manual_payment(order)
    order.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert order.invoice_number is not None
    assert len(grants) == 1
    assert grants[0].payload["license_key"]
    assert not SellerEarning.objects.filter(order=order).exists()
    assert order.ledger_entry is None  # no wallet debit


@pytest.mark.django_db(transaction=True)
def test_confirm_manual_payment_idempotent(customer, qris_plan):
    order, _, _ = checkout(
        customer=customer, plan=qris_plan, checkout_key="ck_qris_4",
        callback_url=CALLBACK_URL, return_url=RETURN_URL, payment_method="qris_static",
    )
    confirm_manual_payment(order)
    inv = Order.objects.get(pk=order.pk).invoice_number
    confirm_manual_payment(order)  # second call
    order.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert order.invoice_number == inv
    assert Grant.objects.filter(order=order).count() == 1


@pytest.mark.django_db(transaction=True)
def test_confirm_manual_payment_recurring_creates_subscription(customer, db):
    seller = _qris_seller(slug="qris-recurring")
    product = ProductFactory(seller=seller, type=Product.Type.RECURRING)
    plan = PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY)
    DeliverableFactory(plan=plan, type="manual")
    order, _, _ = checkout(
        customer=customer, plan=plan, checkout_key="ck_qris_5",
        callback_url=CALLBACK_URL, return_url=RETURN_URL, payment_method="qris_static",
    )
    confirm_manual_payment(order)
    order.refresh_from_db()
    assert order.subscription_id is not None
    assert order.subscription.status == Subscription.Status.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_reject_manual_payment_fails_order(customer, qris_plan):
    order, _, _ = checkout(
        customer=customer, plan=qris_plan, checkout_key="ck_qris_6",
        callback_url=CALLBACK_URL, return_url=RETURN_URL, payment_method="qris_static",
    )
    reject_manual_payment(order, reason="not received")
    order.refresh_from_db()
    assert order.status == Order.Status.FAILED
    assert Grant.objects.filter(order=order).count() == 0


# ── Seller confirmation views ───────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_seller_confirm_payment_view(customer, qris_plan):
    order, _, _ = checkout(
        customer=customer, plan=qris_plan, checkout_key="ck_qris_v1",
        callback_url=CALLBACK_URL, return_url=RETURN_URL, payment_method="qris_static",
    )
    seller = qris_plan.product.seller
    seller.user = UserFactory()
    seller.save()

    client = Client()
    client.force_login(seller.user)
    resp = client.post(reverse("seller:order_confirm_payment", args=[order.pk]))
    assert resp.status_code == 302
    order.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert Grant.objects.filter(order=order).count() == 1


@pytest.mark.django_db(transaction=True)
def test_seller_cannot_confirm_another_sellers_order(customer, qris_plan):
    order, _, _ = checkout(
        customer=customer, plan=qris_plan, checkout_key="ck_qris_v2",
        callback_url=CALLBACK_URL, return_url=RETURN_URL, payment_method="qris_static",
    )
    other = SellerProfile.objects.create(
        name="Other", slug="other-seller", is_approved=True, user=UserFactory(),
    )
    client = Client()
    client.force_login(other.user)
    resp = client.post(reverse("seller:order_confirm_payment", args=[order.pk]))
    assert resp.status_code == 404
    order.refresh_from_db()
    assert order.status == Order.Status.PENDING


# ── Checkout page layout ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_checkout_page_shows_qris_inside_payment_card(qris_plan):
    client = Client()
    resp = client.get(reverse("storefront:checkout", args=[qris_plan.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    # QRIS option lives in the single unified payment-methods card
    assert 'id="payment-methods"' in html
    card = html.split('id="payment-methods"', 1)[1]
    assert 'value="qris_static"' in card
    assert "Static QRIS" in card
    # exactly one payment_method control for qris
    assert html.count('value="qris_static"') == 1
    # buyer can download the static QRIS from the checkout page
    assert "Download QRIS" in html
    assert reverse("storefront:qris_download", args=[qris_plan.product.seller.slug]) in html


@pytest.mark.django_db(transaction=True)
def test_order_status_qris_page_has_download_link(customer, qris_plan):
    order, _, _ = checkout(
        customer=customer, plan=qris_plan, checkout_key="ck_qris_dl",
        callback_url=CALLBACK_URL, return_url=RETURN_URL, payment_method="qris_static",
    )
    c = Client()
    c.force_login(customer.user)
    html = c.get(reverse("storefront:order_status", args=[order.public_id])).content.decode()
    assert "Complete your QRIS payment" in html
    assert "Download QRIS" in html
    assert reverse("storefront:qris_download", args=[qris_plan.product.seller.slug]) in html


@pytest.mark.django_db
def test_qris_download_serves_png(qris_plan):
    seller = qris_plan.product.seller
    resp = Client().get(reverse("storefront:qris_download", args=[seller.slug]))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert 'attachment; filename="QRIS-' in resp["Content-Disposition"]


@pytest.mark.django_db
def test_qris_download_404_when_not_ready(db):
    seller = _qris_seller(slug="no-qris", ready=False)
    resp = Client().get(reverse("storefront:qris_download", args=[seller.slug]))
    assert resp.status_code == 404


# ── Seller settings page ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_settings_page_renders_and_saves_qris(db):
    seller = SellerProfile.objects.create(
        name="Store", slug="settings-store", is_approved=True,
        onboarding_completed=True, user=UserFactory(),
    )
    client = Client()
    client.force_login(seller.user)

    resp = client.get(reverse("seller:settings"))
    assert resp.status_code == 200
    assert b"Static QRIS payment" in resp.content

    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (240, 240), "white").save(buf, format="PNG")
    img = SimpleUploadedFile("qr.png", buf.getvalue(), content_type="image/png")
    resp = client.post(reverse("seller:settings"), {
        "name": "Store", "bio": "", "wa_number": "",
        "payout_bank_name": "", "payout_account_number": "", "payout_account_name": "",
        "custom_domain": "", "ga_tracking_id": "", "fb_pixel_id": "",
        "qris_enabled": "on", "qris_instructions": "Pay the exact amount",
        "qris_image": img,
    })
    assert resp.status_code == 302
    seller.refresh_from_db()
    assert seller.qris_enabled is True
    assert seller.qris_ready is True


@pytest.mark.django_db
def test_settings_rejects_qris_enabled_without_image(db):
    seller = SellerProfile.objects.create(
        name="Store2", slug="settings-store-2", is_approved=True,
        onboarding_completed=True, user=UserFactory(),
    )
    client = Client()
    client.force_login(seller.user)
    resp = client.post(reverse("seller:settings"), {
        "name": "Store2", "bio": "", "wa_number": "",
        "payout_bank_name": "", "payout_account_number": "", "payout_account_name": "",
        "custom_domain": "", "ga_tracking_id": "", "fb_pixel_id": "",
        "qris_enabled": "on",
    })
    assert resp.status_code == 200  # re-rendered with error
    seller.refresh_from_db()
    assert seller.qris_enabled is False


# ── Duration Plan — discount is optional ─────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_duration_plan_zero_discount_charges_full_multiple(customer, db):
    product = ProductFactory(type=Product.Type.RECURRING)
    plan = PlanFactory(
        product=product, price=50_000, interval=Plan.Interval.MONTHLY,
        duration_discounts={"6": 0},
    )
    DeliverableFactory(plan=plan, type="manual")
    _fund(customer, 400_000)
    order, grants, _ = checkout(
        customer=customer, plan=plan, checkout_key="ck_dur_1",
        callback_url=CALLBACK_URL, return_url=RETURN_URL, duration_multiplier=6,
    )
    assert order.amount == 300_000  # 50k * 6, no discount
    assert order.status == Order.Status.PAID
    assert order.subscription_id is not None
