"""Customer Dashboard views — /dashboard/.

All views require login. Customer profile is obtained via request.user.customer.
HTMX partials return HTTP 200 with a fragment; full-page requests return the full template.

Renewal forecast: computed from the subscription with the nearest current_period_end
(ACTIVE + auto_renew=True). Shows a CTA banner when shortfall > 0 and renewal < 24h.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.billing.models import Order, Subscription, TopUp
from apps.dashboard.models import RefundRequest
from apps.licensing.models import Installation, License
from apps.provisioning.models import Grant
from apps.wallet.models import LedgerEntry

logger = logging.getLogger(__name__)

LEDGER_PAGE_SIZE = 20


# ── Helpers ───────────────────────────────────────────────────────────────────

def _customer(request):
    """Return the Customer for the logged-in user. Raises AttributeError if none."""
    return request.user.customer


def _renewal_forecast(customer):
    """Return (next_sub, hours_until, shortfall) for the soonest upcoming renewal.

    Returns (None, None, None) if no active auto-renewing subscription exists.
    """
    next_sub = (
        Subscription.objects.filter(
            customer=customer,
            status=Subscription.Status.ACTIVE,
            auto_renew=True,
        )
        .select_related("plan", "customer__wallet")
        .order_by("current_period_end")
        .first()
    )
    if not next_sub:
        return None, None, None

    now = timezone.now()
    delta = next_sub.current_period_end - now
    hours_until = delta.total_seconds() / 3600

    customer.wallet.refresh_from_db()
    shortfall = max(0, next_sub.plan.price - customer.wallet.balance)
    return next_sub, hours_until, shortfall


# ── Main pages ────────────────────────────────────────────────────────────────

@login_required
def home(request):
    customer = _customer(request)
    customer.wallet.refresh_from_db()

    next_sub, hours_until, shortfall = _renewal_forecast(customer)

    active_subs = (
        Subscription.objects.filter(customer=customer)
        .exclude(status=Subscription.Status.CANCELLED)
        .select_related("plan")
        .order_by("current_period_end")[:5]
    )

    recent_grants = (
        Grant.objects.filter(customer=customer)
        .select_related("order__plan")
        .order_by("-created_at")[:5]
    )

    return render(request, "dashboard/home.html", {
        "customer": customer,
        "wallet": customer.wallet,
        "next_sub": next_sub,
        "hours_until": hours_until,
        "shortfall": shortfall,
        "active_subs": active_subs,
        "recent_grants": recent_grants,
    })


@login_required
def wallet(request):
    customer = _customer(request)
    customer.wallet.refresh_from_db()

    ledger_qs = LedgerEntry.objects.filter(wallet=customer.wallet).order_by("-created_at")
    paginator = Paginator(ledger_qs, LEDGER_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page", 1))

    if request.headers.get("HX-Request"):
        return render(request, "dashboard/partials/ledger_rows.html", {"page": page})

    return render(request, "dashboard/wallet.html", {
        "customer": customer,
        "wallet": customer.wallet,
        "page": page,
    })


@login_required
def ledger_partial(request):
    customer = _customer(request)
    ledger_qs = LedgerEntry.objects.filter(wallet=customer.wallet).order_by("-created_at")
    paginator = Paginator(ledger_qs, LEDGER_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page", 1))
    return render(request, "dashboard/partials/ledger_rows.html", {"page": page})


@login_required
def products(request):
    customer = _customer(request)
    licenses = (
        License.objects.filter(customer=customer)
        .select_related("plan__product", "grant")
        .prefetch_related("installations")
        .order_by("-created_at")
    )
    return render(request, "dashboard/products.html", {
        "customer": customer,
        "licenses": licenses,
    })


@login_required
def devices(request):
    customer = _customer(request)
    installations = (
        Installation.objects.filter(license__customer=customer)
        .select_related("license__plan")
        .order_by("-activated_at")
    )
    return render(request, "dashboard/devices.html", {
        "customer": customer,
        "installations": installations,
    })


@login_required
@require_POST
def deactivate_device(request, pk):
    customer = _customer(request)
    installation = get_object_or_404(
        Installation, pk=pk, license__customer=customer,
        status=Installation.Status.ACTIVE,
    )
    installation.status = Installation.Status.DEACTIVATED
    installation.save(update_fields=["status", "updated_at"])

    from apps.core.audit import log_action
    log_action("device.deactivated", target=installation, meta={"customer_id": customer.pk})

    if request.headers.get("HX-Request"):
        return render(request, "dashboard/partials/device_row.html", {
            "installation": installation,
        })
    return redirect("dashboard:devices")


@login_required
def subscriptions(request):
    customer = _customer(request)
    customer.wallet.refresh_from_db()
    subs = (
        Subscription.objects.filter(customer=customer)
        .select_related("plan")
        .order_by("-current_period_end")
    )

    # Annotate shortfall for each active sub
    subs_with_shortfall = []
    for sub in subs:
        shortfall = max(0, sub.plan.price - customer.wallet.balance) if sub.status == Subscription.Status.ACTIVE else 0
        subs_with_shortfall.append((sub, shortfall))

    return render(request, "dashboard/subscriptions.html", {
        "customer": customer,
        "wallet": customer.wallet,
        "subs_with_shortfall": subs_with_shortfall,
    })


@login_required
@require_POST
def toggle_auto_renew(request, pk):
    customer = _customer(request)
    sub = get_object_or_404(Subscription, pk=pk, customer=customer)
    sub.auto_renew = not sub.auto_renew
    sub.save(update_fields=["auto_renew", "updated_at"])

    if request.headers.get("HX-Request"):
        return render(request, "dashboard/partials/auto_renew_toggle.html", {
            "sub": sub,
        })
    return redirect("dashboard:subscriptions")


@login_required
def invoices(request):
    customer = _customer(request)
    orders = (
        Order.objects.filter(customer=customer, status=Order.Status.PAID)
        .select_related("plan")
        .order_by("-created_at")
    )
    topups = (
        TopUp.objects.filter(customer=customer, status=TopUp.Status.PAID)
        .order_by("-created_at")
    )
    return render(request, "dashboard/invoices.html", {
        "customer": customer,
        "orders": orders,
        "topups": topups,
    })


@login_required
def profile(request):
    customer = _customer(request)
    if request.method == "POST":
        wa = request.POST.get("wa_number", "").strip()
        customer.wa_number = wa
        customer.save(update_fields=["wa_number", "updated_at"])
        messages.success(request, "Profile updated.")
        return redirect("dashboard:profile")
    return render(request, "dashboard/profile.html", {"customer": customer})


@login_required
def support(request):
    customer = _customer(request)
    from apps.core.models import Setting
    wa_support = Setting.get("SUPPORT_WA_NUMBER", "")
    return render(request, "dashboard/support.html", {
        "customer": customer,
        "wa_support": wa_support,
    })


@login_required
def refund_request(request, pk):
    customer = _customer(request)
    order = get_object_or_404(Order, public_id=pk, customer=customer, status=Order.Status.PAID)

    existing = RefundRequest.objects.filter(customer=customer, order=order).first()

    if request.method == "POST":
        if existing:
            messages.warning(request, "Refund request already submitted.")
            return redirect("dashboard:invoices")
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "Please provide a reason.")
            return render(request, "dashboard/refund_request.html", {
                "customer": customer,
                "order": order,
                "existing": existing,
            })
        RefundRequest.objects.create(customer=customer, order=order, reason=reason)
        messages.success(request, "Refund request submitted. We'll review it shortly.")
        return redirect("dashboard:invoices")

    return render(request, "dashboard/refund_request.html", {
        "customer": customer,
        "order": order,
        "existing": existing,
    })
