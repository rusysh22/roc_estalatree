"""Activation API router — /v1/activate, /v1/validate, /v1/deactivate.

Thin HTTP layer; all business logic lives in licensing/services.py.

Auth (H2): ProductSecretAuth checks X-Estalatree-Secret header against
ACTIVATION_API_SECRET Setting. If the Setting is not configured, all requests
pass (dev convenience). Set ACTIVATION_API_SECRET via Admin to enable auth.

Rate limiting is handled inside the service (cache-based, per-key + per-IP).
All endpoints return HTTP 200 with status in body (standard activation API convention).
"""
from ninja import Router, Schema
from ninja.security import APIKeyHeader

from apps.core.models import Setting
from apps.licensing import services

# ── Auth ──────────────────────────────────────────────────────────────────────


class ProductSecretAuth(APIKeyHeader):
    """Optional product secret via X-Estalatree-Secret header.

    H2: if ACTIVATION_API_SECRET Setting is set, all three endpoints require the
    header value to match. If not set (default), all requests pass — suitable for
    development and for operators who prefer license-key-as-sole-credential
    (Keygen / Cryptlex style).

    Set ACTIVATION_API_SECRET via the Admin Setting to enable auth.
    """

    param_name = "X-Estalatree-Secret"

    def authenticate(self, request, key):
        required = Setting.get("ACTIVATION_API_SECRET", "")
        if not required:
            return "open"  # not configured — allow all (dev / key-as-sole-credential)
        return key if key == required else None


_auth = ProductSecretAuth()

router = Router(tags=["activation"], auth=_auth)


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


@router.post("/activate", response=ActivationResponse)
def activate(request, body: ActivateRequest):
    """Register a device and issue an activation token."""
    return services.activate(
        body.license_key,
        body.fingerprint,
        body.machine_name,
        ip_address=_get_ip(request),
    )


@router.post("/validate", response=ActivationResponse)
def validate(request, body: ValidateRequest):
    """Heartbeat — validate token and return a refreshed one."""
    return services.validate(
        body.license_key,
        body.fingerprint,
        body.token,
        ip_address=_get_ip(request),
    )


@router.post("/deactivate", response=ActivationResponse)
def deactivate(request, body: DeactivateRequest):
    """Release a device seat."""
    return services.deactivate(
        body.license_key,
        body.fingerprint,
        ip_address=_get_ip(request),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_ip(request) -> str:
    # LOW: X-Forwarded-For is spoofable; only trust when behind a known proxy.
    # In production, set TRUSTED_PROXY_IPS or strip XFF at the load balancer level.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
