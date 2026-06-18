"""Storefront views — public-facing product catalog, checkout, top-up.

Anonymous visitors can browse; checkout requires a logged-in Customer.
If a user has no Customer profile yet (e.g. fresh Google SSO), one is
created automatically before checkout proceeds.

Top-up-and-buy: if balance < plan price at checkout, the Duitku invoice
is initiated and the user is redirected to the payment page. On webhook
receipt the Order is fulfilled automatically (ADR-015).
"""
import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.billing.models import Order, TopUp
from apps.catalog.models import Plan, Product
from apps.core.models import Setting
from apps.storefront.models import Block, StorePage

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_customer(user):
    """Return (customer, created). Auto-creates Customer + wallet on first visit."""
    from apps.accounts.models import Customer
    customer, created = Customer.objects.get_or_create(user=user)
    if created:
        # Wallet is created by post_save signal in wallet/signals.py
        customer.refresh_from_db()
    return customer, created


def _callback_url(request):
    return request.build_absolute_uri("/billing/webhook/duitku/")


# ── Store page ────────────────────────────────────────────────────────────────

def page(request, slug=None):
    """Public store page — the link-in-bio home."""
    if slug:
        store_page = get_object_or_404(StorePage, slug=slug, is_published=True)
    else:
        store_page = StorePage.objects.filter(is_published=True).first()

    blocks = []
    if store_page:
        blocks = (
            store_page.blocks.filter(is_visible=True)
            .select_related("product")
            .prefetch_related("product__plans")
            .order_by("position")
        )

    return render(request, "storefront/page.html", {
        "store_page": store_page,
        "blocks": blocks,
    })


# ── Product detail ────────────────────────────────────────────────────────────

def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, visibility=Product.Visibility.PUBLIC)
    plans = product.plans.filter(is_active=True).order_by("sort_order", "price")
    return render(request, "storefront/product.html", {
        "product": product,
        "plans": plans,
    })


# ── Checkout ──────────────────────────────────────────────────────────────────

@login_required
def checkout_plan(request, plan_pk):
    plan = get_object_or_404(Plan, pk=plan_pk, is_active=True)
    product = plan.product

    if product.visibility != Product.Visibility.PUBLIC:
        messages.error(request, "Product not available.")
        return redirect("storefront:page")

    customer, _ = _get_or_create_customer(request.user)

    if request.method == "GET":
        customer.wallet.refresh_from_db()
        shortfall = max(0, plan.price - customer.wallet.balance)
        balance_after = customer.wallet.balance - plan.price if shortfall == 0 else 0
        return render(request, "storefront/checkout.html", {
            "plan": plan,
            "product": product,
            "wallet": customer.wallet,
            "shortfall": shortfall,
            "balance_after": balance_after,
        })

    # POST — run checkout
    from apps.billing.checkout import checkout, CheckoutIdempotencyError

    checkout_key = f"ck:{request.user.pk}:{plan.pk}:{uuid.uuid4().hex[:12]}"
    return_url = request.build_absolute_uri(f"/orders/pending/")

    try:
        order, grants, payment_url = checkout(
            customer=customer,
            plan=plan,
            checkout_key=checkout_key,
            callback_url=_callback_url(request),
            return_url=return_url,
        )
    except CheckoutIdempotencyError:
        messages.error(request, "Duplicate checkout — please try again.")
        return redirect("storefront:product", slug=product.slug)

    if payment_url:
        return redirect(payment_url)

    return redirect("storefront:order_status", public_id=order.public_id)


# ── Order status ──────────────────────────────────────────────────────────────

@login_required
def order_status(request, public_id):
    customer, _ = _get_or_create_customer(request.user)
    order = get_object_or_404(Order, public_id=public_id, customer=customer)
    return render(request, "storefront/order_status.html", {
        "order": order,
        "customer": customer,
    })


# ── Top-up ────────────────────────────────────────────────────────────────────

@login_required
def topup(request):
    customer, _ = _get_or_create_customer(request.user)
    customer.wallet.refresh_from_db()

    if request.method == "POST":
        try:
            amount = int(request.POST.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0

        if amount <= 0:
            messages.error(request, "Please enter a valid top-up amount.")
            return render(request, "storefront/topup.html", {
                "customer": customer,
                "wallet": customer.wallet,
            })

        from apps.billing.services import initiate_topup

        try:
            topup_obj, payment_url = initiate_topup(
                customer=customer,
                amount=amount,
                callback_url=_callback_url(request),
                return_url=request.build_absolute_uri("/dashboard/wallet/"),
            )
            return redirect(payment_url)
        except Exception as exc:
            logger.error("topup initiation failed: %s", exc)
            messages.error(request, "Top-up unavailable right now. Please try again.")

    quick_amounts = [
        {"value": v, "label": f"{v:,}"}
        for v in [50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000]
    ]
    return render(request, "storefront/topup.html", {
        "customer": customer,
        "wallet": customer.wallet,
        "quick_amounts": quick_amounts,
    })


# ── Contact (WA lead) ─────────────────────────────────────────────────────────

def contact(request, product_pk):
    product = get_object_or_404(
        Product, pk=product_pk,
        type=Product.Type.CONTACT,
        visibility=Product.Visibility.PUBLIC,
    )

    if request.method == "POST":
        from apps.crm.models import Lead

        name = request.POST.get("name", "").strip()
        contact_val = request.POST.get("contact", "").strip()

        if not name or not contact_val:
            messages.error(request, "Name and contact are required.")
            return render(request, "storefront/contact.html", {
                "product": product,
            })

        Lead.objects.create(name=name, contact=contact_val, product=product)

        wa = product.wa_number or Setting.get("SUPPORT_WA_NUMBER", "")
        if wa:
            from apps.notifications.whatsapp import normalize_number
            wa_url = f"https://wa.me/{normalize_number(wa)}?text=Hi%2C+I'm+interested+in+{product.name}"
            return redirect(wa_url)

        messages.success(request, "Thanks! We'll be in touch.")
        return redirect("storefront:page")

    return render(request, "storefront/contact.html", {"product": product})
