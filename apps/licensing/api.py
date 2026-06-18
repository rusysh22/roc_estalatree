"""Activation API router — /v1/activate, /v1/validate, /v1/deactivate.

Thin HTTP layer; all business logic lives in licensing/services.py.
Rate limiting is handled inside the service (cache-based, per-key + per-IP).
All endpoints return HTTP 200 with status in body (standard activation API convention).
"""
from ninja import Router, Schema

from apps.licensing import services

router = Router(tags=["activation"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ActivateRequest(Schema):
    license_key: str
    fingerprint: str
    machine_name: str = ""


class ValidateRequest(Schema):
    license_key: str
    fingerprint: str
    token: str


class DeactivateRequest(Schema):
    license_key: str
    fingerprint: str


class ActivationResponse(Schema):
    status: str
    token: str = ""
    expires_at: str = ""
    grace_days: int = 0
    message: str = ""
    entitlements: dict = {}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/activate", response=ActivationResponse, auth=None)
def activate(request, body: ActivateRequest):
    """Register a device and issue an activation token."""
    ip = _get_ip(request)
    return services.activate(
        body.license_key,
        body.fingerprint,
        body.machine_name,
        ip_address=ip,
    )


@router.post("/validate", response=ActivationResponse, auth=None)
def validate(request, body: ValidateRequest):
    """Heartbeat — validate token and return a refreshed one."""
    ip = _get_ip(request)
    return services.validate(
        body.license_key,
        body.fingerprint,
        body.token,
        ip_address=ip,
    )


@router.post("/deactivate", response=ActivationResponse, auth=None)
def deactivate(request, body: DeactivateRequest):
    """Release a device seat."""
    ip = _get_ip(request)
    return services.deactivate(
        body.license_key,
        body.fingerprint,
        ip_address=ip,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
