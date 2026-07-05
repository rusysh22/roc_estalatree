"""Shared branding helpers for anything rendered outside a normal HTTP request
(emails, PDFs) — no {% static %}/request context available there.
"""
import base64
from functools import lru_cache


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    """Base64 data: URI for the brand logo, inlined so emails/PDFs never depend
    on an external image fetch (avoids missed-collectstatic or client-blocked-images
    breakage). finders.find() looks at STATICFILES_DIRS directly, so this works
    whether or not collectstatic has run.
    """
    from django.contrib.staticfiles import finders

    path = finders.find("images/brand/logo-mark-email.png")
    if not path:
        return ""
    with open(path, "rb") as f:
        data = f.read()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def site_url() -> str:
    from django.conf import settings
    return f"{settings.SITE_URL_SCHEME}://{settings.SITE_DOMAIN}"


def base_branding_context() -> dict:
    from django.conf import settings
    return {
        "site_name": settings.SITE_NAME,
        "site_domain": settings.SITE_DOMAIN,
        "site_url": site_url(),
        "logo_data_uri": logo_data_uri(),
    }
