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


@pytest.mark.xfail(reason="Phase 5: Activation API not yet implemented", strict=False)
@pytest.mark.django_db
def test_golden_path_activate():
    """OSS product activates a license key; token returned; seat counted."""
    raise NotImplementedError


@pytest.mark.xfail(reason="Phase 6: Subscription renewal not yet implemented", strict=False)
@pytest.mark.django_db
def test_golden_path_renew():
    """Renewal job deducts balance, extends subscription, grant stays active."""
    raise NotImplementedError
