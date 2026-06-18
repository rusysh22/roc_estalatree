"""Core utilities shared across all apps."""
import secrets
import string


def generate_public_id(prefix: str, length: int = 16) -> str:
    """Generate a prefixed, URL-safe public ID.

    Args:
        prefix: e.g. "ord_", "top_", "lead_"
        length: number of random characters (default 16)

    Example: "ord_a3f8kz92mn1p4qvw"
    """
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(length))
    return f"{prefix}{random_part}"