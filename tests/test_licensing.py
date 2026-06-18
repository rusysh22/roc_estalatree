"""Tests for Phase 5 — LicenseKeyProvisioner + Activation Service.

Provisioner tests (5a):
 1. provision creates License + Grant with correct links
 2. provision sets seat_limit from plan
 3. suspend cascades to Grant + License
 4. resume cascades to Grant + License
 5. revoke cascades to Grant + License
 6. provision with subscription links both models

Activation service tests (5b):
 7. activate new fingerprint → active + token + Installation created
 8. activate same fingerprint again → idempotent, same seat, fresh token
 9. activate seat_full → seat_full status
10. activate revoked license → revoked status
11. activate suspended license → suspended status
12. validate active token → active + fresh token
13. validate expired token (beyond grace) → expired
14. validate within grace period → active
15. validate maintenance mode → always active
16. deactivate frees seat
"""
import time
from unittest.mock import patch

import pytest

from apps.core.models import Setting
from apps.licensing.models import Installation, License
from apps.licensing.services import activate, deactivate, validate, _issue_token
from apps.provisioning.models import Deliverable, Grant
from tests.factories import CustomerFactory, DeliverableFactory, PlanFactory, ProductFactory


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def customer(db):
    return CustomerFactory()


@pytest.fixture
def license_plan(db):
    from apps.catalog.models import Plan, Product
    product = ProductFactory(type=Product.Type.ONE_TIME)
    plan = PlanFactory(product=product, price=100_000, interval=Plan.Interval.NONE, seat_limit=2)
    DeliverableFactory(plan=plan, type="license_key")
    return plan


@pytest.fixture
def order_and_grant(customer, license_plan):
    """Full checkout: funded wallet → Order + Grant + License."""
    from apps.billing.checkout import checkout
    from apps.wallet.models import LedgerEntry
    from apps.wallet.services import credit

    credit(
        customer.wallet, 100_000,
        LedgerEntry.Type.ADJUSTMENT,
        ref="test:licensing:fund",
        note="test setup",
    )
    order, grants, _ = checkout(
        customer=customer,
        plan=license_plan,
        checkout_key="ck:licensing:001",
        callback_url="https://example.com/webhook/",
        return_url="https://example.com/return/",
    )
    return order, grants[0]


@pytest.fixture
def active_license(order_and_grant):
    _, grant = order_and_grant
    return License.objects.get(grant=grant)


# ── 5a: Provisioner tests ─────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_provision_creates_license_and_grant(order_and_grant):
    """Provision creates a License + Grant with correct links and status."""
    order, grant = order_and_grant
    license = License.objects.get(grant=grant)

    assert grant.type == Deliverable.Type.LICENSE_KEY
    assert grant.status == Grant.Status.ACTIVE
    assert grant.order == order
    assert grant.payload["license_key"] == license.key

    assert license.status == License.Status.ACTIVE
    assert license.customer == order.customer
    assert license.plan == order.plan
    assert license.grant == grant
    assert license.key  # auto-generated XXXX-XXXX-XXXX


@pytest.mark.django_db(transaction=True)
def test_provision_seat_limit_from_plan(order_and_grant, license_plan):
    """Provisioner takes seat_limit from plan.seat_limit when config has no override."""
    _, grant = order_and_grant
    license = License.objects.get(grant=grant)
    assert license.seat_limit == license_plan.seat_limit  # 2


@pytest.mark.django_db
def test_suspend_cascades_to_grant_and_license(active_license):
    """suspend() sets Grant.SUSPENDED and License.SUSPENDED."""
    from apps.provisioning.registry import get as get_provisioner
    provisioner = get_provisioner("license_key")
    grant = active_license.grant

    provisioner.suspend(grant)

    grant.refresh_from_db()
    active_license.refresh_from_db()
    assert grant.status == Grant.Status.SUSPENDED
    assert active_license.status == License.Status.SUSPENDED


@pytest.mark.django_db
def test_resume_cascades_to_grant_and_license(active_license):
    """resume() sets Grant.ACTIVE and License.ACTIVE."""
    from apps.provisioning.registry import get as get_provisioner
    provisioner = get_provisioner("license_key")
    grant = active_license.grant

    provisioner.suspend(grant)
    provisioner.resume(grant)

    grant.refresh_from_db()
    active_license.refresh_from_db()
    assert grant.status == Grant.Status.ACTIVE
    assert active_license.status == License.Status.ACTIVE


@pytest.mark.django_db
def test_revoke_cascades_to_grant_and_license(active_license):
    """revoke() sets Grant.REVOKED and License.REVOKED."""
    from apps.provisioning.registry import get as get_provisioner
    provisioner = get_provisioner("license_key")
    grant = active_license.grant

    provisioner.revoke(grant)

    grant.refresh_from_db()
    active_license.refresh_from_db()
    assert grant.status == Grant.Status.REVOKED
    assert active_license.status == License.Status.REVOKED


@pytest.mark.django_db(transaction=True)
def test_provision_recurring_links_subscription(customer, db):
    """Recurring plan: Grant.subscription and License.subscription both set."""
    from apps.billing.checkout import checkout
    from apps.catalog.models import Plan, Product
    from apps.billing.models import Subscription
    from apps.wallet.models import LedgerEntry
    from apps.wallet.services import credit

    product = ProductFactory(type=Product.Type.RECURRING)
    plan = PlanFactory(product=product, price=50_000, interval=Plan.Interval.MONTHLY)
    DeliverableFactory(plan=plan, type="license_key")

    credit(customer.wallet, 100_000, LedgerEntry.Type.ADJUSTMENT,
           ref="test:recurring:fund", note="")

    order, grants, _ = checkout(
        customer=customer, plan=plan,
        checkout_key="ck:recurring:001",
        callback_url="https://example.com/webhook/",
        return_url="https://example.com/return/",
    )
    grant = grants[0]
    license = License.objects.get(grant=grant)
    sub = Subscription.objects.get(customer=customer, plan=plan)

    assert grant.subscription == sub
    assert license.subscription == sub


# ── 5b: Activation service tests ─────────────────────────────────────────────

@pytest.mark.django_db
def test_activate_new_fingerprint(active_license):
    """New fingerprint: Installation created, active status, token returned."""
    result = activate(active_license.key, fingerprint="fp-001", machine_name="PC-01")

    assert result["status"] == "active"
    assert result["token"]
    assert result["expires_at"]
    assert Installation.objects.filter(
        license=active_license, fingerprint="fp-001", status=Installation.Status.ACTIVE
    ).exists()


@pytest.mark.django_db
def test_activate_idempotent_same_fingerprint(active_license):
    """Same fingerprint re-activate returns fresh token without consuming a new seat."""
    activate(active_license.key, fingerprint="fp-002", machine_name="PC-02")
    active_license.refresh_from_db()
    count_before = active_license.active_seat_count

    result = activate(active_license.key, fingerprint="fp-002", machine_name="PC-02")

    assert result["status"] == "active"
    assert result["token"]
    active_license.refresh_from_db()
    assert active_license.active_seat_count == count_before  # no extra seat consumed


@pytest.mark.django_db
def test_activate_seat_full(active_license):
    """All seats taken: seat_full status returned."""
    # seat_limit = 2; fill both
    activate(active_license.key, fingerprint="fp-A")
    activate(active_license.key, fingerprint="fp-B")

    result = activate(active_license.key, fingerprint="fp-C")
    assert result["status"] == "seat_full"


@pytest.mark.django_db
def test_activate_revoked_license(active_license):
    """Revoked license returns revoked status."""
    License.objects.filter(pk=active_license.pk).update(status=License.Status.REVOKED)

    result = activate(active_license.key, fingerprint="fp-rev")
    assert result["status"] == "revoked"


@pytest.mark.django_db
def test_activate_suspended_license(active_license):
    """Suspended license returns suspended status."""
    License.objects.filter(pk=active_license.pk).update(status=License.Status.SUSPENDED)

    result = activate(active_license.key, fingerprint="fp-sus")
    assert result["status"] == "suspended"


@pytest.mark.django_db
def test_validate_active_token(active_license):
    """Valid token within TTL → active + fresh token."""
    token, _ = _issue_token(active_license.key, "fp-val-001")
    activate(active_license.key, fingerprint="fp-val-001")  # create installation

    result = validate(active_license.key, "fp-val-001", token)

    assert result["status"] == "active"
    assert result["token"]  # fresh token issued


@pytest.mark.django_db
def test_validate_expired_beyond_grace(active_license):
    """Token expired beyond TTL + grace period → expired."""
    Setting.objects.update_or_create(
        key="ACTIVATION_TOKEN_TTL_DAYS", defaults={"value": "1"}
    )
    Setting.objects.update_or_create(
        key="ACTIVATION_GRACE_DAYS", defaults={"value": "0"}
    )

    past = time.time() - 5 * 86400  # 5 days ago — beyond 1-day TTL + 0 grace
    with patch("django.core.signing.time.time", return_value=past):
        token, _ = _issue_token(active_license.key, "fp-exp-001")

    activate(active_license.key, fingerprint="fp-exp-001")

    result = validate(active_license.key, "fp-exp-001", token)
    assert result["status"] == "expired"


@pytest.mark.django_db
def test_validate_within_grace_period(active_license):
    """Token past TTL but within grace → still active (grace period)."""
    Setting.objects.update_or_create(
        key="ACTIVATION_TOKEN_TTL_DAYS", defaults={"value": "1"}
    )
    Setting.objects.update_or_create(
        key="ACTIVATION_GRACE_DAYS", defaults={"value": "5"}
    )

    # Issue token 3 days ago — beyond 1-day TTL, within 5-day grace
    past = time.time() - 3 * 86400
    with patch("django.core.signing.time.time", return_value=past):
        token, _ = _issue_token(active_license.key, "fp-grace-001")

    activate(active_license.key, fingerprint="fp-grace-001")

    result = validate(active_license.key, "fp-grace-001", token)
    assert result["status"] == "active"


@pytest.mark.django_db
def test_validate_maintenance_mode_bypasses_expiry(active_license):
    """MAINTENANCE_MODE=true always returns active — panic control."""
    Setting.objects.update_or_create(
        key="MAINTENANCE_MODE", defaults={"value": "true"}
    )
    Setting.objects.update_or_create(
        key="ACTIVATION_TOKEN_TTL_DAYS", defaults={"value": "1"}
    )
    Setting.objects.update_or_create(
        key="ACTIVATION_GRACE_DAYS", defaults={"value": "0"}
    )

    # Issue an already-expired token
    past = time.time() - 10 * 86400
    with patch("django.core.signing.time.time", return_value=past):
        token, _ = _issue_token(active_license.key, "fp-maint-001")

    result = validate(active_license.key, "fp-maint-001", token)
    assert result["status"] == "active"

    # Cleanup
    Setting.objects.filter(key="MAINTENANCE_MODE").update(value="false")


@pytest.mark.django_db
def test_deactivate_frees_seat(active_license):
    """Deactivate releases the Installation slot; seat count drops."""
    activate(active_license.key, fingerprint="fp-deact-001")
    active_license.refresh_from_db()
    assert active_license.active_seat_count == 1

    result = deactivate(active_license.key, fingerprint="fp-deact-001")
    assert result["status"] == "deactivated"

    active_license.refresh_from_db()
    assert active_license.active_seat_count == 0


@pytest.mark.django_db
def test_activate_invalid_key():
    """Unknown license key returns invalid status."""
    result = activate("ZZZZ-ZZZZ-ZZZZ", fingerprint="fp-none")
    assert result["status"] == "invalid"


# ── Phase 5 review tests ──────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_activate_seat_limit_not_exceeded_sequentially(active_license):
    """H1: seat limit is never exceeded even under rapid sequential activations."""
    limit = active_license.seat_limit  # 2
    results = [activate(active_license.key, fingerprint=f"fp-race-{i}") for i in range(limit + 1)]

    statuses = [r["status"] for r in results]
    assert statuses.count("active") == limit
    assert statuses.count("seat_full") == 1

    active_license.refresh_from_db()
    assert active_license.active_seat_count == limit


@pytest.mark.django_db
def test_validate_after_deactivate_returns_deactivated(active_license):
    """M1: validate after deactivation returns 'deactivated' — old token no longer works."""
    activate(active_license.key, fingerprint="fp-m1-val")
    token, _ = _issue_token(active_license.key, "fp-m1-val")

    deactivate(active_license.key, fingerprint="fp-m1-val")

    result = validate(active_license.key, "fp-m1-val", token)
    assert result["status"] == "deactivated"


@pytest.mark.django_db
def test_revoke_writes_audit_log(active_license):
    """M2: revoke() writes an AuditLog entry."""
    from apps.core.models import AuditLog
    from apps.provisioning.registry import get as get_provisioner

    provisioner = get_provisioner("license_key")
    grant = active_license.grant

    before_count = AuditLog.objects.filter(action="license.revoked").count()
    provisioner.revoke(grant)
    after_count = AuditLog.objects.filter(action="license.revoked").count()

    assert after_count == before_count + 1
    entry = AuditLog.objects.filter(action="license.revoked").latest("created_at")
    assert entry.target_type == "Grant"
    assert entry.target_id == str(grant.pk)


@pytest.mark.django_db
def test_suspend_writes_audit_log(active_license):
    """M2: suspend() writes an AuditLog entry."""
    from apps.core.models import AuditLog
    from apps.provisioning.registry import get as get_provisioner

    provisioner = get_provisioner("license_key")
    grant = active_license.grant

    before_count = AuditLog.objects.filter(action="license.suspended").count()
    provisioner.suspend(grant)
    after_count = AuditLog.objects.filter(action="license.suspended").count()

    assert after_count == before_count + 1


@pytest.mark.django_db
def test_api_requires_secret_when_configured(client, active_license):
    """H2: when ACTIVATION_API_SECRET is set, requests without the header get 401."""
    import json
    from apps.core.models import Setting

    Setting.objects.update_or_create(
        key="ACTIVATION_API_SECRET", defaults={"value": "super-secret-123"}
    )
    try:
        payload = json.dumps({"license_key": active_license.key, "fingerprint": "fp-h2"})

        # No header → 401
        response = client.post(
            "/v1/activate",
            data=payload,
            content_type="application/json",
        )
        assert response.status_code == 401

        # Wrong header → 401
        response = client.post(
            "/v1/activate",
            data=payload,
            content_type="application/json",
            headers={"X-Estalatree-Secret": "wrong"},
        )
        assert response.status_code == 401

        # Correct header → 200
        response = client.post(
            "/v1/activate",
            data=payload,
            content_type="application/json",
            headers={"X-Estalatree-Secret": "super-secret-123"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "active"
    finally:
        Setting.objects.filter(key="ACTIVATION_API_SECRET").delete()
