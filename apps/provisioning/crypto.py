"""Fernet encryption helper for the Secret model.

Key derivation: takes Django SECRET_KEY (or PROVISIONING_SECRET_KEY env var),
derives a 32-byte Fernet key via HKDF-SHA256 so any valid SECRET_KEY works.
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    raw_key = os.environ.get("PROVISIONING_SECRET_KEY") or _django_secret_key()
    # HKDF-lite: SHA-256(raw_key) → 32 bytes → url-safe base64
    key_bytes = hashlib.sha256(raw_key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def _django_secret_key() -> str:
    from django.conf import settings
    return settings.SECRET_KEY


def encrypt(plaintext: str) -> str:
    """Encrypt a string; returns Fernet token as a unicode string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token; returns the original plaintext."""
    return _fernet().decrypt(ciphertext.encode()).decode()
