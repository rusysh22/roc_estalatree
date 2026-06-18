"""Licensing utilities: license key generation with collision-safe retry."""
import secrets

from django.db import IntegrityError

# Crockford Base32: 0-9 A-H J-N P-T V-Z (no I L O U — no ambiguous chars)
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_license_key() -> str:
    """Generate one XXXX-XXXX-XXXX Crockford Base32 key. See ADR-007."""
    group = lambda: "".join(secrets.choice(_CROCKFORD) for _ in range(4))
    return f"{group()}-{group()}-{group()}"


def assign_unique_license_key(instance, max_attempts: int = 5) -> None:
    """Set a unique license key on a License instance, retrying on collision (M3 fix)."""
    from apps.licensing.models import License

    for _ in range(max_attempts):
        candidate = generate_license_key()
        if not License.objects.filter(key=candidate).exists():
            instance.key = candidate
            return
    raise RuntimeError(f"Could not generate a unique license key after {max_attempts} attempts")