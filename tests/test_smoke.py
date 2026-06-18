"""Golden-path smoke test stub.

This test suite validates the full business flow end-to-end:
    top-up → buy → activate → renew

Each assertion is a stub (marked xfail) until the underlying phase is implemented.
Remove xfail marks as phases land and make the assertions real.

DO NOT remove this file — the smoke test is a permanent quality gate per CONVENTIONS.md.
"""
import pytest


@pytest.mark.django_db
def test_server_boots():
    """Django check passes: settings load, apps register without errors."""
    from django.test import Client

    client = Client()
    # HEAD on admin login should return 200 or 302 (redirect to login)
    response = client.get("/admin/login/")
    assert response.status_code in (200, 302)


@pytest.mark.django_db
def test_provisioner_registry_importable():
    """Provisioner registry imports and is empty at Phase 0."""
    from apps.provisioning.registry import registered_types

    # No provisioners registered yet; this confirms the registry is importable.
    assert isinstance(registered_types(), list)


@pytest.mark.django_db
def test_core_setting_get_default():
    """Setting.get() returns the default when key is absent."""
    from apps.core.models import Setting

    assert Setting.get("nonexistent_key", default="fallback") == "fallback"


@pytest.mark.django_db
def test_audit_log_immutable_in_admin(admin_client):
    """AuditLog has no add/change/delete permissions in Django Admin."""
    from django.contrib.admin.sites import site
    from django.test import RequestFactory

    from apps.core.models import AuditLog

    factory = RequestFactory()
    request = factory.get("/")
    request.user = admin_client  # superuser

    model_admin = site._registry.get(AuditLog)
    if model_admin is None:
        pytest.skip("AuditLog not registered in admin yet")

    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)


# ── Stubs (xfail until phase lands) ──────────────────────────────────────────

@pytest.mark.xfail(reason="Phase 3: Duitku top-up not yet implemented", strict=False)
@pytest.mark.django_db
def test_golden_path_topup():
    """Customer tops up via Duitku sandbox; balance increases via ledger."""
    raise NotImplementedError


@pytest.mark.xfail(reason="Phase 4: Checkout not yet implemented", strict=False)
@pytest.mark.django_db
def test_golden_path_buy():
    """Customer buys a one-time product; order created, grant issued, balance deducted."""
    raise NotImplementedError


@pytest.mark.django_db(transaction=True)
def test_golden_path_activate():
    """OSS product activates a license key; token returned; seat counted."""
    from apps.billing.checkout import checkout
    from apps.catalog.models import Plan, Product
    from apps.licensing.models import Installation, License
    from apps.licensing.services import activate
    from apps.wallet.models import LedgerEntry
    from apps.wallet.services import credit
    from tests.factories import CustomerFactory, DeliverableFactory, PlanFactory, ProductFactory

    customer = CustomerFactory()
    credit(
        customer.wallet,
        100_000,
        LedgerEntry.Type.ADJUSTMENT,
        ref="smoke:activate:fund",
        note="smoke test setup",
    )

    product = ProductFactory(type=Product.Type.ONE_TIME)
    plan = PlanFactory(product=product, price=100_000, interval=Plan.Interval.NONE)
    DeliverableFactory(plan=plan, type="license_key")

    order, grants, _ = checkout(
        customer=customer,
        plan=plan,
        checkout_key="smoke:activate:ck001",
        callback_url="https://example.com/webhook/",
        return_url="https://example.com/return/",
    )
    assert len(grants) == 1
    license = License.objects.get(grant=grants[0])
    assert license.status == License.Status.ACTIVE

    result = activate(license.key, fingerprint="smoke-fp-001", machine_name="SMOKE-PC")
    assert result["status"] == "active"
    assert result["token"]
    assert Installation.objects.filter(
        license=license, fingerprint="smoke-fp-001", status=Installation.Status.ACTIVE
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_golden_path_renew():
    """Renewal job deducts balance, extends subscription, grant stays active."""
    from apps.billing.checkout import checkout
    from apps.billing.models import Subscription
    from apps.billing.subscription_service import renew_subscription
    from apps.catalog.models import Plan, Product
    from apps.licensing.models import License
    from apps.provisioning.models import Grant
    from apps.wallet.models import LedgerEntry
    from apps.wallet.services import credit
    from tests.factories import CustomerFactory, DeliverableFactory, PlanFactory, ProductFactory

    customer = CustomerFactory()
    credit(customer.wallet, 200_000, LedgerEntry.Type.ADJUSTMENT,
           ref="smoke:renew:fund", note="smoke test setup")

    product = ProductFactory(type=Product.Type.RECURRING)
    plan = PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY)
    DeliverableFactory(plan=plan, type="license_key")

    _, grants, _ = checkout(
        customer=customer,
        plan=plan,
        checkout_key="smoke:renew:ck001",
        callback_url="https://example.com/cb/",
        return_url="https://example.com/ret/",
    )
    assert len(grants) == 1

    sub = Subscription.objects.get(customer=customer, plan=plan)
    original_end = sub.current_period_end
    customer.wallet.refresh_from_db()
    wallet_after_purchase = customer.wallet.balance

    renewed = renew_subscription(sub)

    assert renewed is True
    sub.refresh_from_db()
    assert sub.status == Subscription.Status.ACTIVE
    assert sub.current_period_end > original_end

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == wallet_after_purchase - plan.price

    grant = grants[0]
    grant.refresh_from_db()
    assert grant.status == Grant.Status.ACTIVE

    license = License.objects.get(grant=grant)
    assert license.status == License.Status.ACTIVE
