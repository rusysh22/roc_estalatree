"""Licensing utilities: license key generation."""
import secrets

# Crockford Base32: digits + uppercase alpha, minus ambiguous I O U L and 0 1.
# Charset: 0-9 A-H J-N P-T V-Z  (32 chars, no I L O U)
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_license_key() -> str:
    """Generate a unique XXXX-XXXX-XXXX license key (plain hash, no prefix). See ADR-007."""
    group = lambda: "".join(secrets.choice(_CROCKFORD) for _ in range(4))
    return f"{group()}-{group()}-{group()}"