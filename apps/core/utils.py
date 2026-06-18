"""Core utilities shared across all apps."""
import secrets
import string

from django.db import IntegrityError


def generate_public_id(prefix: str, length: int = 16) -> str:
    """Generate a prefixed, URL-safe public ID (not collision-safe alone — use with_unique_public_id).

    Example: "ord_a3f8kz92mn1p4qvw"
    """
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(length))
    return f"{prefix}{random_part}"


def assign_unique_public_id(instance, prefix: str, field: str = "public_id", max_attempts: int = 5) -> None:
    """Set a unique public_id on a model instance, retrying on collision (M3 fix).

    Call this from model.save() before super().save().
    Raises RuntimeError if max_attempts exhausted (astronomically unlikely).
    """
    from django.db import transaction

    for _ in range(max_attempts):
        candidate = generate_public_id(prefix)
        if not type(instance).objects.filter(**{field: candidate}).exists():
            setattr(instance, field, candidate)
            return
    raise RuntimeError(f"Could not generate a unique {field} after {max_attempts} attempts")