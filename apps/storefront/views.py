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
    sold_counts = {}
    if store_page:
        blocks = (
            store_page.blocks.filter(is_visible=True)
            .select_related("product__seller")
            .prefetch_related("product__plans")
            .order_by("position")
        )
        # Annotate each product with sold count (paid orders only)
        product_pks = [b.product_id for b in blocks if b.product_id]
        if product_pks:
            from django.db.models import Count as DCount
            sold_qs = (
                Order.objects.filter(
                    plan__product_id__in=product_pks,
                    status=Order.Status.PAID,
                )
                .values("plan__product_id")
                .annotate(cnt=DCount("id"))
            )
            sold_counts = {row["plan__product_id"]: row["cnt"] for row in sold_qs}

    return render(request, "storefront/page.html", {
        "store_page": store_page,
        "blocks": blocks,
        "sold_counts": sold_counts,
    })


# ── Product detail ────────────────────────────────────────────────────────────

def product_detail(request, slug):
    product = get_object_or_404(
        Product, slug=slug,
        visibility__in=[Product.Visibility.PUBLIC, Product.Visibility.UNLISTED],
    )
    plans = product.plans.filter(is_active=True).order_by("sort_order", "price")
    sold_count = Order.objects.filter(
        plan__product=product, status=Order.Status.PAID
    ).count()
    return render(request, "storefront/product.html", {
        "product": product,
        "plans": plans,
        "sold_count": sold_count,
    })


# ── Checkout ──────────────────────────────────────────────────────────────────

@login_required
def checkout_plan(request, plan_pk):
    plan = get_object_or_404(Plan, pk=plan_pk, is_active=True)
    product = plan.product

    if product.visibility == Product.Visibility.DRAFT:
        messages.error(request, "Product not available.")
        return redirect("storefront:page")

    customer, _ = _get_or_create_customer(request.user)

    _SESSION_KEY = f"ck_token_{plan_pk}"

    if request.method == "GET":
        # Generate a stable idempotency token for this checkout intent.
        # Reusing the same token on POST prevents double-charge on double-click.
        checkout_token = uuid.uuid4().hex
        request.session[_SESSION_KEY] = checkout_token

        customer.wallet.refresh_from_db()

        # Coupon preview (GET ?coupon_code=XXX)
        from apps.billing.models import Coupon
        discount = 0
        coupon_obj = None
        coupon_error = None
        coupon_code_get = request.GET.get("coupon_code", "").strip().upper()
        if coupon_code_get:
            try:
                coupon_obj = Coupon.objects.get(code=coupon_code_get)
                valid, reason = coupon_obj.is_valid_for(plan)
                if valid:
                    discount = coupon_obj.compute_discount(plan.price)
                else:
                    coupon_error = reason
                    coupon_obj = None
            except Coupon.DoesNotExist:
                coupon_error = "Coupon code not found."

        effective_price = max(0, plan.price - discount)
        shortfall = max(0, effective_price - customer.wallet.balance)
        balance_after = customer.wallet.balance - effective_price if shortfall == 0 else 0

        return render(request, "storefront/checkout.html", {
            "plan": plan,
            "product": product,
            "wallet": customer.wallet,
            "shortfall": shortfall,
            "balance_after": balance_after,
            "checkout_token": checkout_token,
            "coupon": coupon_obj,
            "coupon_code": coupon_code_get,
            "coupon_error": coupon_error,
            "discount": discount,
            "effective_price": effective_price,
        })

    # POST — run checkout
    from apps.billing.checkout import checkout, CheckoutIdempotencyError
    from apps.billing.models import Coupon

    checkout_token = request.POST.get("checkout_token") or request.session.get(_SESSION_KEY, uuid.uuid4().hex)
    checkout_key = f"ck:{request.user.pk}:{plan.pk}:{checkout_token}"
    return_url = request.build_absolute_uri("/orders/pending/")

    # Resolve coupon code if provided
    coupon = None
    coupon_code = request.POST.get("coupon_code", "").strip().upper()
    if coupon_code:
        try:
            coupon_obj = Coupon.objects.get(code=coupon_code)
            valid, reason = coupon_obj.is_valid_for(plan)
            if valid:
                coupon = coupon_obj
            else:
                messages.warning(request, f"Coupon not applicable: {reason}")
        except Coupon.DoesNotExist:
            messages.warning(request, "Coupon code not found.")

    try:
        order, grants, payment_url = checkout(
            customer=customer,
            plan=plan,
            checkout_key=checkout_key,
            coupon=coupon,
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
    order = get_object_or_404(
        Order.objects.select_related("plan__product"),
        public_id=public_id,
        customer=customer,
    )
    return render(request, "storefront/order_status.html", {
        "order": order,
        "customer": customer,
    })


# ── Top-up ────────────────────────────────────────────────────────────────────

@login_required
def topup(request):
    customer, _ = _get_or_create_customer(request.user)
    customer.wallet.refresh_from_db()

    MIN_TOPUP = int(Setting.get("MIN_TOPUP", "10000"))
    MAX_TOPUP = int(Setting.get("MAX_TOPUP", "50000000"))

    if request.method == "POST":
        try:
            amount = int(request.POST.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0

        if amount < MIN_TOPUP:
            messages.error(request, f"Minimum top-up is Rp{MIN_TOPUP:,}.")
        elif amount > MAX_TOPUP:
            messages.error(request, f"Maximum top-up is Rp{MAX_TOPUP:,}.")
        else:
            from apps.billing.services import initiate_topup

            try:
                bonus_pct = int(Setting.get("TOPUP_BONUS_PERCENT", "0"))
                bonus = amount * bonus_pct // 100
                topup_obj, payment_url = initiate_topup(
                    customer=customer,
                    amount=amount,
                    bonus=bonus,
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
        "min_topup": MIN_TOPUP,
        "max_topup": MAX_TOPUP,
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
