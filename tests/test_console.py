"""Tests for Phase 10 — Operator Console."""
import pytest
from django.urls import reverse

from apps.accounts.models import Customer, User
from apps.billing.models import Order, Subscription
from apps.core.models import AuditLog, Setting
from apps.dashboard.models import RefundRequest
from apps.wallet.models import LedgerEntry


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def staff_user(db):
    return User.objects.create_user(email="staff@example.com", password="pw", is_staff=True)


@pytest.fixture
def superuser(db):
    return User.objects.create_user(email="super@example.com", password="pw", is_staff=True, is_superuser=True)


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(email="user@example.com", password="pw")


@pytest.fixture
def staff_client(client, staff_user):
    from django.contrib.auth.models import Group
    op_group, _ = Group.objects.get_or_create(name="Operator")
    staff_user.groups.add(op_group)
    client.force_login(staff_user)
    return client


@pytest.fixture
def super_client(client, superuser):
    client.force_login(superuser)
    return client


@pytest.fixture
def customer_with_wallet(db):
    user = User.objects.create_user(email="cust@example.com", password="pw")
    customer = Customer.objects.create(user=user)
    return customer


# ── Access control ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_cockpit_requires_staff(client, regular_user):
    client.force_login(regular_user)
    resp = client.get(reverse("console:cockpit"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_cockpit_anonymous_redirects(client):
    resp = client.get(reverse("console:cockpit"))
    assert resp.status_code == 302
    assert "/admin/login/" in resp["Location"]


@pytest.mark.django_db
def test_settings_requires_superuser(staff_client):
    resp = staff_client.get(reverse("console:settings"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_setup_requires_superuser(staff_client):
    resp = staff_client.get(reverse("console:setup"))
    assert resp.status_code == 403


# ── Cockpit ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_cockpit_returns_200(staff_client):
    resp = staff_client.get(reverse("console:cockpit"))
    assert resp.status_code == 200
    assert b"Cockpit" in resp.content


@pytest.mark.django_db
def test_cockpit_kpi_shows_balance_liability(staff_client, customer_with_wallet):
    from apps.wallet.services import credit
    wallet = customer_with_wallet.wallet
    credit(wallet, 50_000, LedgerEntry.Type.ADJUSTMENT, ref="test:kpi:1")
    resp = staff_client.get(reverse("console:cockpit"))
    assert resp.status_code == 200
    assert b"50" in resp.content  # 50,000 appears in KPI


# ── Customer list & 360 ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_customer_list_returns_200(staff_client, customer_with_wallet):
    resp = staff_client.get(reverse("console:customer_list"))
    assert resp.status_code == 200
    assert b"cust@example.com" in resp.content


@pytest.mark.django_db
def test_customer_list_search(staff_client, customer_with_wallet):
    resp = staff_client.get(reverse("console:customer_list") + "?q=cust@")
    assert resp.status_code == 200
    assert b"cust@example.com" in resp.content


@pytest.mark.django_db
def test_customer_360_returns_200(staff_client, customer_with_wallet):
    resp = staff_client.get(reverse("console:customer_360", args=[customer_with_wallet.pk]))
    assert resp.status_code == 200
    assert b"cust@example.com" in resp.content


# ── Manual credit ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_manual_credit_requires_superuser(staff_client, customer_with_wallet):
    resp = staff_client.post(
        reverse("console:manual_credit", args=[customer_with_wallet.pk]),
        {"amount": "25000", "reason": "Goodwill"},
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_manual_credit_adds_balance(super_client, customer_with_wallet):
    before = customer_with_wallet.wallet.balance
    resp = super_client.post(
        reverse("console:manual_credit", args=[customer_with_wallet.pk]),
        {"amount": "25000", "reason": "Goodwill"},
    )
    assert resp.status_code == 302
    customer_with_wallet.wallet.refresh_from_db()
    assert customer_with_wallet.wallet.balance == before + 25_000


@pytest.mark.django_db
def test_manual_credit_writes_audit_log(super_client, customer_with_wallet):
    super_client.post(
        reverse("console:manual_credit", args=[customer_with_wallet.pk]),
        {"amount": "10000", "reason": "Test credit"},
    )
    assert AuditLog.objects.filter(action="wallet.manual_credit").exists()


@pytest.mark.django_db
def test_manual_credit_requires_reason(super_client, customer_with_wallet):
    before = customer_with_wallet.wallet.balance
    resp = super_client.post(
        reverse("console:manual_credit", args=[customer_with_wallet.pk]),
        {"amount": "10000", "reason": ""},
    )
    assert resp.status_code == 302
    customer_with_wallet.wallet.refresh_from_db()
    assert customer_with_wallet.wallet.balance == before  # unchanged


# ── Refund flow ───────────────────────────────────────────────────────────────

@pytest.fixture
def pending_refund(db, customer_with_wallet):
    from apps.catalog.models import Plan, Product
    product = Product.objects.create(name="P", slug="p-refund", type=Product.Type.ONE_TIME)
    plan = Plan.objects.create(product=product, name="Basic", price=100_000, interval="monthly")
    order = Order.objects.create(customer=customer_with_wallet, plan=plan, amount=100_000, status=Order.Status.PAID)
    return RefundRequest.objects.create(customer=customer_with_wallet, order=order, reason="Test refund")


@pytest.mark.django_db
def test_refund_detail_requires_superuser(staff_client, pending_refund):
    resp = staff_client.get(reverse("console:refund_detail", args=[pending_refund.pk]))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_refund_detail_returns_200(super_client, pending_refund):
    resp = super_client.get(reverse("console:refund_detail", args=[pending_refund.pk]))
    assert resp.status_code == 200
    assert b"Test refund" in resp.content


@pytest.mark.django_db
def test_refund_approve_credits_wallet(super_client, pending_refund, customer_with_wallet):
    before = customer_with_wallet.wallet.balance
    resp = super_client.post(reverse("console:refund_approve", args=[pending_refund.pk]), {"admin_note": ""})
    assert resp.status_code == 302
    pending_refund.refresh_from_db()
    assert pending_refund.status == RefundRequest.Status.APPROVED
    customer_with_wallet.wallet.refresh_from_db()
    assert customer_with_wallet.wallet.balance == before + 100_000


@pytest.mark.django_db
def test_refund_approve_marks_order_refunded(super_client, pending_refund):
    super_client.post(reverse("console:refund_approve", args=[pending_refund.pk]), {"admin_note": ""})
    pending_refund.order.refresh_from_db()
    assert pending_refund.order.status == Order.Status.REFUNDED


@pytest.mark.django_db
def test_refund_approve_idempotent_double_submit(super_client, pending_refund, customer_with_wallet):
    """Deterministic ref prevents double-credit on double-submit."""
    before = customer_with_wallet.wallet.balance
    super_client.post(reverse("console:refund_approve", args=[pending_refund.pk]), {"admin_note": ""})
    # second submit: refund is no longer PENDING — credit() idempotency via same ref
    super_client.post(reverse("console:refund_approve", args=[pending_refund.pk]), {"admin_note": ""})
    customer_with_wallet.wallet.refresh_from_db()
    assert customer_with_wallet.wallet.balance == before + 100_000  # credited exactly once


@pytest.mark.django_db
def test_refund_reject_sets_status(super_client, pending_refund):
    resp = super_client.post(
        reverse("console:refund_reject", args=[pending_refund.pk]),
        {"admin_note": "Policy violation"},
    )
    assert resp.status_code == 302
    pending_refund.refresh_from_db()
    assert pending_refund.status == RefundRequest.Status.REJECTED
    assert pending_refund.admin_note == "Policy violation"


# ── Extend subscription ───────────────────────────────────────────────────────

@pytest.fixture
def active_sub(db, customer_with_wallet):
    from apps.catalog.models import Plan, Product
    from django.utils import timezone
    product = Product.objects.create(name="Psub", slug="p-sub-console", type=Product.Type.ONE_TIME)
    plan = Plan.objects.create(product=product, name="Monthly", price=50_000, interval="monthly")
    return Subscription.objects.create(
        customer=customer_with_wallet,
        plan=plan,
        status=Subscription.Status.ACTIVE,
        current_period_end=timezone.now() + timezone.timedelta(days=3),
    )


@pytest.mark.django_db
def test_extend_subscription(staff_client, active_sub):
    old_end = active_sub.current_period_end
    resp = staff_client.post(
        reverse("console:extend_subscription", args=[active_sub.pk]),
        {"days": "7"},
    )
    assert resp.status_code == 302
    active_sub.refresh_from_db()
    from django.utils import timezone
    assert active_sub.current_period_end > old_end


# ── Settings ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_settings_view_superuser(super_client):
    resp = super_client.get(reverse("console:settings"))
    assert resp.status_code == 200
    assert b"MAINTENANCE_MODE" in resp.content


@pytest.mark.django_db
def test_settings_post_saves_setting(super_client):
    resp = super_client.post(reverse("console:settings"), {"ACTIVATION_TOKEN_TTL_DAYS": "14"})
    assert resp.status_code == 302
    assert Setting.get("ACTIVATION_TOKEN_TTL_DAYS") == "14"


# ── CSV export ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_export_orders_csv(staff_client):
    resp = staff_client.get(reverse("console:export_csv", args=["orders"]))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    assert b"public_id" in resp.content


@pytest.mark.django_db
def test_export_ledger_csv_no_crash(staff_client):
    resp = staff_client.get(reverse("console:export_csv", args=["ledger"]))
    assert resp.status_code == 200
    assert b"ref" in resp.content  # M1: e.type not e.entry_type


@pytest.mark.django_db
def test_export_invalid_model_404(staff_client):
    resp = staff_client.get(reverse("console:export_csv", args=["secret_data"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_settings_canonical_keys_saved(super_client):
    """H1: canonical key names match what services read."""
    resp = super_client.post(reverse("console:settings"), {
        "ACTIVATION_TOKEN_TTL_DAYS": "14",
        "MAINTENANCE_MODE": "true",
        "GLOBAL_GRACE_EXTENSION_DAYS": "2",
    })
    assert resp.status_code == 302
    assert Setting.get("ACTIVATION_TOKEN_TTL_DAYS") == "14"
    assert Setting.get("MAINTENANCE_MODE") == "true"
    assert Setting.get("GLOBAL_GRACE_EXTENSION_DAYS") == "2"


# ── Audit log ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_audit_log_view_returns_200(staff_client):
    resp = staff_client.get(reverse("console:audit_log"))
    assert resp.status_code == 200
    assert b"Audit Log" in resp.content


# ── Setup checklist ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_setup_view_superuser(super_client):
    resp = super_client.get(reverse("console:setup"))
    assert resp.status_code == 200
    assert b"First-run Setup" in resp.content
