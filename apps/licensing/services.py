"""Activation service — activate, validate, deactivate licenses.

Token: django.core.signing.TimestampSigner (HMAC-SHA256, no extra deps).
All mutation paths log every attempt for abuse monitoring.

Setting keys (via Setting model; zero-downtime change via Admin):
  ACTIVATION_TOKEN_TTL_DAYS     int, default 7  — normal token lifetime
  ACTIVATION_GRACE_DAYS         int, default 3  — extra days where validate still passes
  GLOBAL_GRACE_EXTENSION_DAYS   int, default 0  — superadmin panic: extend all grace globally
  MAINTENANCE_MODE              "true"/"false", default false
                                — if true, validate always returns active (no brick during outage)

Rate limiting: in-process cache (LocMemCache in dev, Redis cache in prod).
  Per license key: 20 requests / 60 s
  Per IP address:  60 requests / 60 s
"""
import logging
import time

from django.core.cache import cache
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils import timezone

from apps.core.models import Setting

logger = logging.getLogger(__name__)

_TOKEN_SALT = "estalatree-activation-v1"
_RATE_WINDOW = 60  # seconds
_RATE_LIMIT_KEY = 20
_RATE_LIMIT_IP = 60


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ttl_seconds() -> int:
    return int(Setting.get("ACTIVATION_TOKEN_TTL_DAYS", "7")) * 86400


def _grace_seconds() -> int:
    days = int(Setting.get("ACTIVATION_GRACE_DAYS", "3"))
    extension = int(Setting.get("GLOBAL_GRACE_EXTENSION_DAYS", "0"))
    return (days + extension) * 86400


def _issue_token(license_key: str, fingerprint: str) -> tuple[str, str]:
    """Return (signed_token, iso_expires_at)."""
    ttl = _ttl_seconds()
    value = f"{license_key}:{fingerprint}"
    token = TimestampSigner(salt=_TOKEN_SALT).sign(value)
    expires_at = timezone.now() + timezone.timedelta(seconds=ttl)
    return token, expires_at.isoformat()


def _verify_token(token: str, license_key: str, fingerprint: str) -> str:
    """Return 'active', 'grace', or 'expired'/'invalid'."""
    signer = TimestampSigner(salt=_TOKEN_SALT)
    expected = f"{license_key}:{fingerprint}"

    # Step 1: check signature only (no age limit)
    try:
        value = signer.unsign(token)
    except BadSignature:
        return "invalid"

    if value != expected:
        return "invalid"

    ttl = _ttl_seconds()
    grace = _grace_seconds()

    # Step 2: within normal TTL?
    try:
        signer.unsign(token, max_age=ttl)
        return "active"
    except SignatureExpired:
        pass

    # Step 3: within grace period?
    try:
        signer.unsign(token, max_age=ttl + grace)
        return "grace"
    except SignatureExpired:
        return "expired"


def _get_entitlements(license) -> dict:
    try:
        return license.grant.get_entitlements()
    except Exception:
        return {}


def _check_rate_limit(identifier: str, limit: int) -> bool:
    """Return True if the caller has exceeded the rate limit."""
    key = f"rate:activation:{identifier}"
    count = cache.get(key, 0)
    if count >= limit:
        return True
    cache.set(key, count + 1, _RATE_WINDOW)
    return False


# ── Public API ────────────────────────────────────────────────────────────────

def activate(
    license_key_str: str,
    fingerprint: str,
    machine_name: str = "",
    *,
    ip_address: str = "",
) -> dict:
    """Register a new installation and issue an activation token.

    Idempotent: same fingerprint on same license returns the existing seat + fresh token.
    Rate limited: per license key and per IP.
    """
    from apps.licensing.models import Installation, License

    # Rate limiting
    if _check_rate_limit(f"key:{license_key_str}", _RATE_LIMIT_KEY):
        logger.warning("activate: rate limit exceeded for key %s", license_key_str[:4])
        return {"status": "rate_limited", "message": "Too many requests — retry later"}
    if ip_address and _check_rate_limit(f"ip:{ip_address}", _RATE_LIMIT_IP):
        logger.warning("activate: rate limit exceeded for IP %s", ip_address)
        return {"status": "rate_limited", "message": "Too many requests — retry later"}

    # Resolve license
    try:
        license = License.objects.select_related("grant__deliverable__plan").get(
            key=license_key_str
        )
    except License.DoesNotExist:
        logger.info("activate: invalid key (first 4: %s)", license_key_str[:4])
        return {"status": "invalid", "message": "License key not found"}

    # Status guards
    if license.status == License.Status.REVOKED:
        return {"status": "revoked", "message": "License has been revoked"}
    if license.status == License.Status.SUSPENDED:
        return {"status": "suspended", "message": "License is currently suspended"}
    if license.status == License.Status.EXPIRED:
        return {"status": "expired", "message": "License has expired"}

    # Idempotent: existing active installation → fresh token, no new seat
    existing = license.installations.filter(
        fingerprint=fingerprint, status=Installation.Status.ACTIVE
    ).first()
    if existing:
        Installation.objects.filter(pk=existing.pk).update(last_seen=timezone.now())
        token, expires_at = _issue_token(license_key_str, fingerprint)
        logger.info(
            "activate: idempotent key=%s fp=%s...", license_key_str[:4], fingerprint[:8]
        )
        return {
            "status": "active",
            "token": token,
            "expires_at": expires_at,
            "grace_days": int(Setting.get("ACTIVATION_GRACE_DAYS", "3")),
            "entitlements": _get_entitlements(license),
        }

    # Seat limit check
    if not license.seats_available:
        return {
            "status": "seat_full",
            "message": f"All {license.seat_limit} seat(s) are in use. "
                       "Deactivate a device to free a slot.",
        }

    # Create installation + issue token
    Installation.objects.create(
        license=license,
        fingerprint=fingerprint,
        name=machine_name,
        status=Installation.Status.ACTIVE,
        last_seen=timezone.now(),
    )
    token, expires_at = _issue_token(license_key_str, fingerprint)
    grace_days = int(Setting.get("ACTIVATION_GRACE_DAYS", "3"))

    logger.info(
        "activate: new installation key=%s fp=%s... machine=%r",
        license_key_str[:4], fingerprint[:8], machine_name,
    )
    return {
        "status": "active",
        "token": token,
        "expires_at": expires_at,
        "grace_days": grace_days,
        "entitlements": _get_entitlements(license),
    }


def validate(
    license_key_str: str,
    fingerprint: str,
    token: str,
    *,
    ip_address: str = "",
) -> dict:
    """Periodic heartbeat — refresh the token while the license is active.

    Maintenance mode: if MAINTENANCE_MODE=true, always returns active (panic control).
    Grace period: if token is expired but within grace window, still returns active.
    """
    from apps.licensing.models import Installation, License

    # Maintenance mode — panic control (never brick customers during outage)
    if Setting.get("MAINTENANCE_MODE", "false").strip().lower() == "true":
        new_token, expires_at = _issue_token(license_key_str, fingerprint)
        logger.info("validate: maintenance mode active — bypassing checks for key %s", license_key_str[:4])
        return {"status": "active", "token": new_token, "expires_at": expires_at}

    # Rate limiting
    if _check_rate_limit(f"key:{license_key_str}", _RATE_LIMIT_KEY):
        logger.warning("validate: rate limit exceeded for key %s", license_key_str[:4])
        return {"status": "rate_limited", "message": "Too many requests — retry later"}
    if ip_address and _check_rate_limit(f"ip:{ip_address}", _RATE_LIMIT_IP):
        return {"status": "rate_limited", "message": "Too many requests — retry later"}

    # Verify token signature + timing
    token_status = _verify_token(token, license_key_str, fingerprint)
    if token_status == "invalid":
        logger.warning("validate: invalid token for key %s", license_key_str[:4])
        return {"status": "invalid", "message": "Invalid or tampered token — re-activate"}

    # Resolve license (check for revocation/suspension since token was issued)
    try:
        license = License.objects.select_related("grant__deliverable__plan").get(
            key=license_key_str
        )
    except License.DoesNotExist:
        return {"status": "invalid", "message": "License not found"}

    if license.status == License.Status.REVOKED:
        return {"status": "revoked", "message": "License has been revoked"}
    if license.status == License.Status.SUSPENDED:
        return {"status": "suspended", "message": "License is currently suspended"}

    # Update last_seen for heartbeat tracking
    Installation.objects.filter(
        license=license,
        fingerprint=fingerprint,
        status=Installation.Status.ACTIVE,
    ).update(last_seen=timezone.now())

    if token_status in ("active", "grace"):
        new_token, expires_at = _issue_token(license_key_str, fingerprint)
        return {
            "status": "active",
            "token": new_token,
            "expires_at": expires_at,
            "entitlements": _get_entitlements(license),
        }

    # expired
    logger.info("validate: expired token for key %s", license_key_str[:4])
    return {"status": "expired", "message": "Token has expired — please re-activate"}


def deactivate(
    license_key_str: str,
    fingerprint: str,
    *,
    ip_address: str = "",
) -> dict:
    """Release an installation seat. Idempotent — safe to call if already deactivated."""
    from apps.licensing.models import Installation, License

    if _check_rate_limit(f"key:{license_key_str}", _RATE_LIMIT_KEY):
        return {"status": "rate_limited", "message": "Too many requests — retry later"}

    try:
        license = License.objects.get(key=license_key_str)
    except License.DoesNotExist:
        return {"status": "invalid", "message": "License key not found"}

    updated = Installation.objects.filter(
        license=license,
        fingerprint=fingerprint,
        status=Installation.Status.ACTIVE,
    ).update(status=Installation.Status.DEACTIVATED)

    logger.info(
        "deactivate: key=%s fp=%s... updated=%d", license_key_str[:4], fingerprint[:8], updated
    )
    return {"status": "deactivated"}
