"""Shared model-level validators.

Kept dependency-free (no imports from other apps) so any app can use them
without creating an import cycle.
"""
import re

from django.core.exceptions import ValidationError


def normalize_wa_number(raw: str) -> str:
    """Normalize an Indonesian WhatsApp number to bare international form.

    081xxx  -> 6281xxx
    +62xxx  -> 62xxx
    62xxx   -> 62xxx (unchanged)
    Non-digits (spaces, dashes, parentheses) are stripped.
    """
    digits = re.sub(r"\D", "", (raw or "").strip())
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits


def validate_wa_number(value: str) -> None:
    """Validate a stored WhatsApp number.

    Blank is allowed (Django skips validators for empty values). A non-blank
    value must normalize to `62` + 8..13 digits (Indonesian MSISDN range).
    """
    if not value:
        return
    number = normalize_wa_number(value)
    if not re.fullmatch(r"62\d{8,13}", number):
        raise ValidationError(
            "Enter a valid Indonesian WhatsApp number, e.g. 081234567890 or 6281234567890."
        )
