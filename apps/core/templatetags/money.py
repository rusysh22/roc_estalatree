"""Template filters for rupiah money formatting."""
from django import template

from apps.core.formatting import format_rupiah

register = template.Library()


@register.simple_tag(takes_context=True)
def wallet_balance(context):
    """Return the logged-in user's wallet balance (0 if no wallet)."""
    user = context.get("request", None) and context["request"].user
    if not user or not user.is_authenticated:
        return 0
    try:
        return user.customer.wallet.balance
    except Exception:
        return 0


@register.simple_tag(takes_context=True)
def user_surfaces(context):
    """Return dict of available surfaces for the current user: {dashboard, console, seller}."""
    user = context.get("request", None) and context["request"].user
    if not user or not user.is_authenticated:
        return {}
    surfaces = {}
    try:
        user.customer  # noqa: B018
        surfaces["dashboard"] = True
    except Exception:
        surfaces["dashboard"] = False
    surfaces["console"] = user.is_superuser or user.groups.filter(name="Operator").exists()
    try:
        from apps.accounts.models import SellerProfile
        surfaces["seller"] = SellerProfile.objects.filter(user=user, is_approved=True).exists()
    except Exception:
        surfaces["seller"] = False
    return surfaces


@register.filter
def dict_get(d, key):
    """Lookup d[key] in a template. Works for integer keys unlike dot notation."""
    try:
        return d.get(key) or d.get(int(key))
    except (TypeError, ValueError, AttributeError):
        return None


@register.filter
def rupiah(value):
    """Format value as dot-grouped rupiah: 99000 -> Rp99.000"""
    return format_rupiah(value)


@register.filter
def rupiah_signed(value):
    """Format value as signed rupiah: +100000 -> +Rp100.000, -99000 -> -Rp99.000"""
    return format_rupiah(value, signed=True)
