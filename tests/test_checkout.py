"""Tests for the checkout service (Phase 4).

Covers:
1. Free plan → Order(PAID, amount=0) + Grant created, no payment_url
2. One-time paid plan with sufficient balance → debit + Order(PAID) + Grant
3. Recurring plan → debit + Order(PAID) + Subscription created + Grant
4. Insufficient balance → Order(PENDING) + TopUp(delta) + payment_url returned
5. Top-up-and-buy: webhook credit triggers Order completion + Grant
6. Same checkout_key returns existing Order (idempotent retry)
7. Contact-type plan raises ContactPlanError
"""
import pytest
from django.utils import timezone

from apps.billing.checkout import ContactPlanError, checkout, complete_pending_order
from apps.billing.models import Order, Subscription, TopUp
from apps.catalog.models import Plan, Product
from apps.provisioning.models import Grant
from apps.wallet.models import LedgerEntry
from tests.factories import CustomerFactory, DeliverableFactory, PlanFactory, ProductFactory


# ── Shared fixtures ───────────────────────────────────────────────────────────

CALLBACK_URL = "https://example.com/billing/webhook/duitku/"
RETURN_URL = "https://example.com/billing/topup/return/"


class MockDuitkuClient:
    """Stub Duitku client — no network calls."""

    def create_invoice(self, merchant_order_id, amount, product_details, email,
                       callback_url, return_url, expiry_period=1440):
        from apps.billing.duitku import InvoiceResult
        return InvoiceResult(
            payment_url=f"https://sandbox.duitku.com/pay/{merchant_order_id}",
            va_number="1234567890",
            reference=f"REF-{merchant_order_id}",
        )

    def check_transaction(self, merchant_order_id):
        raise NotImplementedError("not used in checkout tests")

    def verify_webhook_signature(self, merchant_code, amount, merchant_order_id, signature):
        return True

    def build_webhook_signature(self, merchant_order_id, amount):
        return "mock-signature"


@pytest.fixture
def customer(db):
    c = CustomerFactory()
    return c


@pytest.fixture
def free_plan(db):
    product = ProductFactory(type=Product.Type.FREE)
    plan = PlanFactory(product=product, price=0, interval=Plan.Interval.NONE)
    DeliverableFactory(plan=plan, type="manual")
    return plan


@pytest.fixture
def one_time_plan(db):
    product = ProductFactory(type=Product.Type.ONE_TIME)
    plan = PlanFactory(product=product, price=100_000, interval=Plan.Interval.NONE)
    DeliverableFactory(plan=plan, type="manual")
    return plan


@pytest.fixture
def recurring_plan(db):
    product = ProductFactory(type=Product.Type.RECURRING)
    plan = PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY)
    DeliverableFactory(plan=plan, type="manual")
    return plan


@pytest.fixture
def contact_plan(db):
    product = ProductFactory(type=Product.Type.CONTACT)
    plan = PlanFactory(product=product, price=0, interval=Plan.Interval.NONE)
    return plan


def _fund_wallet(customer, amount):
    """Directly credit wallet for test setup (bypasses Duitku)."""
    from apps.wallet.services import credit
    credit(
        wallet=customer.wallet,
        amount=amount,
        entry_type=LedgerEntry.Type.ADJUSTMENT,
        ref=f"test:fund:{customer.pk}:{amount}",
        note="Test setup credit",
    )
    customer.wallet.refresh_from_db()


# ── Test cases ────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_checkout_free_plan(customer, free_plan):
    """Free plan: Order(PAID, 0) + Grant created, no payment URL."""
    order, grants, payment_url = checkout(
        customer=customer,
        plan=free_plan,
        checkout_key="ck_free_001",
        callback_url=CALLBACK_URL,
        return_url=RETURN_URL,
    )

    assert order.status == Order.Status.PAID
    assert order.amount == 0
    assert payment_url is None
    assert len(grants) == 1
    assert grants[0].status == Grant.Status.ACTIVE
    assert grants[0].customer == customer
    # Wallet untouched
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0


@pytest.mark.django_db(transaction=True)
def test_checkout_paid_sufficient_balance(customer, one_time_plan):
    """Paid plan with sufficient balance: wallet debited, Order(PAID), Grant created."""
    _fund_wallet(customer, 200_000)

    order, grants, payment_url = checkout(
        customer=customer,
        plan=one_time_plan,
        checkout_key="ck_paid_001",
        callback_url=CALLBACK_URL,
        return_url=RETURN_URL,
    )

    assert order.status == Order.Status.PAID
    assert order.amount == 100_000
    assert payment_url is None
    assert len(grants) == 1

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 100_000  # 200_000 - 100_000

    debit_entry = LedgerEntry.objects.get(ref=f"order:{order.public_id}")
    assert debit_entry.amount == -100_000
    assert debit_entry.type == LedgerEntry.Type.PURCHASE


@pytest.mark.django_db(transaction=True)
def test_checkout_recurring_creates_subscription(customer, recurring_plan):
    """Recurring plan: Subscription created with correct period_end."""
    _fund_wallet(customer, 100_000)

    order, grants, payment_url = checkout(
        customer=customer,
        plan=recurring_plan,
        checkout_key="ck_rec_001",
        callback_url=CALLBACK_URL,
        return_url=RETURN_URL,
    )

    assert order.status == Order.Status.PAID
    assert payment_url is None
    assert len(grants) == 1

    sub = Subscription.objects.get(customer=customer, plan=recurring_plan)
    assert sub.status == Subscription.Status.ACTIVE
    # period_end should be ~1 month from now
    assert sub.current_period_end > timezone.now()


@pytest.mark.django_db(transaction=True)
def test_checkout_insufficient_balance(customer, one_time_plan):
    """Insufficient balance: Order(PENDING) created, TopUp for delta, payment_url returned."""
    _fund_wallet(customer, 30_000)  # need 100_000

    order, grants, payment_url = checkout(
        customer=customer,
        plan=one_time_plan,
        checkout_key="ck_insuf_001",
        duitku_client=MockDuitkuClient(),
        callback_url=CALLBACK_URL,
        return_url=RETURN_URL,
    )

    assert order.status == Order.Status.PENDING
    assert order.amount == 100_000
    assert grants == []
    assert payment_url is not None
    assert "sandbox.duitku.com" in payment_url

    topup = TopUp.objects.get(checkout_order=order)
    assert topup.amount == 70_000  # delta: 100_000 - 30_000
    assert topup.status == TopUp.Status.PENDING
    # Wallet balance unchanged
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 30_000


@pytest.mark.django_db(transaction=True)
def test_topup_and_buy_completes_order(customer, one_time_plan):
    """After TopUp credit via webhook, linked Order is completed and Grant created."""
    _fund_wallet(customer, 30_000)

    # Start top-up-and-buy flow
    order, grants, payment_url = checkout(
        customer=customer,
        plan=one_time_plan,
        checkout_key="ck_tab_001",
        duitku_client=MockDuitkuClient(),
        callback_url=CALLBACK_URL,
        return_url=RETURN_URL,
    )
    assert order.status == Order.Status.PENDING
    assert grants == []

    topup = TopUp.objects.get(checkout_order=order)
    delta = topup.amount  # 70_000

    # Simulate webhook success — credit the wallet with delta
    from apps.billing.services import _apply_topup_success
    applied = _apply_topup_success(topup)

    assert applied is True

    # Order should now be PAID
    order.refresh_from_db()
    assert order.status == Order.Status.PAID

    # Grant should exist
    grants_after = list(Grant.objects.filter(customer=customer))
    assert len(grants_after) == 1
    assert grants_after[0].status == Grant.Status.ACTIVE

    # Wallet balance: 30_000 + 70_000 (credit) - 100_000 (purchase) = 0
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0


@pytest.mark.django_db(transaction=True)
def test_checkout_idempotent_same_key(customer, one_time_plan):
    """Same checkout_key returns the same Order without double-charging."""
    _fund_wallet(customer, 300_000)

    order1, grants1, _ = checkout(
        customer=customer,
        plan=one_time_plan,
        checkout_key="ck_idem_001",
        callback_url=CALLBACK_URL,
        return_url=RETURN_URL,
    )

    # Second call with same key
    order2, grants2, _ = checkout(
        customer=customer,
        plan=one_time_plan,
        checkout_key="ck_idem_001",
        callback_url=CALLBACK_URL,
        return_url=RETURN_URL,
    )

    assert order1.pk == order2.pk

    # Wallet debited only once
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 200_000  # 300_000 - 100_000

    # Only one debit entry
    entries = LedgerEntry.objects.filter(type=LedgerEntry.Type.PURCHASE)
    assert entries.count() == 1


@pytest.mark.django_db(transaction=True)
def test_checkout_contact_plan_raises(customer, contact_plan):
    """Contact-type plan raises ContactPlanError — cannot be purchased via checkout."""
    with pytest.raises(ContactPlanError):
        checkout(
            customer=customer,
            plan=contact_plan,
            checkout_key="ck_contact_001",
            callback_url=CALLBACK_URL,
            return_url=RETURN_URL,
        )
