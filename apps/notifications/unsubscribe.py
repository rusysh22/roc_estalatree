"""Signed one-click unsubscribe links for notification emails (ADR-022, N.7)."""
from django.core import signing

_SALT = "notifications.unsubscribe"
_MAX_AGE = 60 * 60 * 24 * 90  # links stay valid for 90 days


def make_token(customer_id: int) -> str:
    return signing.dumps({"c": customer_id}, salt=_SALT)


def read_token(token: str) -> int | None:
    try:
        data = signing.loads(token, salt=_SALT, max_age=_MAX_AGE)
        return int(data["c"])
    except (signing.BadSignature, signing.SignatureExpired, KeyError, ValueError, TypeError):
        return None


def unsubscribe_url(customer) -> str:
    from django.urls import reverse

    from apps.core.branding import site_url
    path = reverse("notifications:unsubscribe", args=[make_token(customer.pk)])
    return f"{site_url()}{path}"


def email_footer(customer) -> str:
    return (
        "\n\n—\n"
        f"Manage notifications: {unsubscribe_url(customer)}"
    )
