"""Ed25519 signing for the entitlement envelope returned by /v1/activate and /v1/validate.

Contract: the licensed product verifies `entitlement_signature` against a public
key baked into its own build (see that product's docs/signed_entitlements.md).
The Marketplace signs the UTF-8 bytes of `entitlement` serialized with JSON
keys sorted, no whitespace, and `,`/`:` as the only separators — the product
side must reproduce this exact canonicalization to verify.

Security: MARKETPLACE_ED25519_PRIVATE_KEY_B64 is env-only, never the Setting
model/DB — same rationale as DUITKU_API_KEY (apps/billing/duitku.py) so it
can't leak via Admin or a DB backup.
"""
import base64
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class EntitlementSigningError(Exception):
    pass


def _private_key() -> Ed25519PrivateKey:
    raw_b64 = os.environ.get("MARKETPLACE_ED25519_PRIVATE_KEY_B64", "")
    if not raw_b64:
        raise EntitlementSigningError(
            "MARKETPLACE_ED25519_PRIVATE_KEY_B64 not configured (env only, never DB/Setting)."
        )
    try:
        seed = base64.b64decode(raw_b64)
        return Ed25519PrivateKey.from_private_bytes(seed)
    except Exception as exc:
        raise EntitlementSigningError(
            "MARKETPLACE_ED25519_PRIVATE_KEY_B64 is not a valid base64 32-byte Ed25519 seed."
        ) from exc


def canonical_json(entitlement: dict) -> bytes:
    """Sorted keys, no whitespace, raw UTF-8 (not \\uXXXX-escaped) — must match the
    product's verifier byte-for-byte (deskit_interport/licensing/entitlements.py
    canonical_entitlement_payload)."""
    return json.dumps(
        entitlement, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sign_entitlement(entitlement: dict) -> str:
    """Return the base64 Ed25519 signature over the canonical JSON bytes.

    Raises EntitlementSigningError if the private key isn't configured.
    """
    signature = _private_key().sign(canonical_json(entitlement))
    return base64.b64encode(signature).decode()
