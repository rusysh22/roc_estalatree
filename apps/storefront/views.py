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
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.accounts.models import SellerProfile
from apps.billing.models import Order, TopUp
from apps.catalog.models import Plan, Product, ProductReview
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


def _payment_methods(amount: int):
    """Fetch Duitku payment methods for the given amount. Returns [] on gateway failure."""
    from apps.billing.duitku import DuitkuClient, DuitkuError

    try:
        client = DuitkuClient.from_settings()
        return client.get_payment_methods(amount)
    except DuitkuError:
        logger.exception("Failed to fetch Duitku payment methods")
        return []


# Display order + label for grouped payment method rendering.
PAYMENT_METHOD_GROUPS = [
    ("va", "Bank Transfer / Virtual Account"),
    ("qris", "QRIS"),
    ("ewallet", "E-Wallet"),
    ("retail", "Convenience Store"),
    ("cc", "Credit / Debit Card"),
    ("other", "Other"),
]


def _group_payment_methods(methods):
    """Group a flat list of PaymentMethod into [{key, label, methods}], empty groups omitted."""
    buckets = {key: [] for key, _label in PAYMENT_METHOD_GROUPS}
    for pm in methods:
        buckets.setdefault(pm.method_type, buckets["other"]).append(pm)
    return [
        {"key": key, "label": label, "methods": buckets[key]}
        for key, label in PAYMENT_METHOD_GROUPS
        if buckets[key]
    ]


# ── Analytics helpers ─────────────────────────────────────────────────────────

def _emit_event(request, event_type, *, product=None, plan=None):
    """Fire a PageEvent row. Never raises — analytics must not break the user flow."""
    try:
        from apps.storefront.models import PageEvent
        PageEvent.objects.create(
            event=event_type,
            product=product,
            plan=plan,
            session_key=request.session.session_key or "",
        )
    except Exception:
        pass


def _record_affiliate_commission(request, order) -> None:
    """Create AffiliateCommission for a paid order if a ref code is in session. Never raises."""
    try:
        ref_code = request.session.pop("affiliate_ref", None)
        if not ref_code:
            return
        from apps.billing.models import AffiliateLink, AffiliateCommission
        link = AffiliateLink.objects.filter(code=ref_code, is_active=True).first()
        if not link:
            return
        # Only apply if the link is for this seller/product or unrestricted
        product = order.plan.product
        if link.product_id and link.product_id != product.pk:
            return
        if link.seller_id and product.seller_id and link.seller_id != product.seller_id:
            return
        amount = order.amount * link.commission_rate // 100
        AffiliateCommission.objects.get_or_create(
            order=order,
            defaults={"link": link, "amount": amount},
        )
    except Exception:
        logger.exception("Failed to record affiliate commission for order %s", order.pk)


# ── Marketplace landing page ─────────────────────────────────────────────────

def landing(request):
    """Public marketplace home — platform-wide discovery, not a specific seller.

    Trending products, featured sellers, and testimonials are drawn from
    across the whole marketplace (only PUBLIC products from active+approved
    sellers). Individual seller pages live at /<slug>/ (see `page` below).
    """
    trending_products = (
        Product.objects.filter(
            visibility=Product.Visibility.PUBLIC,
            seller__is_active=True,
            seller__is_approved=True,
        )
        .select_related("seller")
        .prefetch_related(Prefetch(
            "plans", queryset=Plan.objects.filter(is_active=True).order_by("price")
        ))
        .annotate(paid_order_count=Count(
            "plans__orders",
            filter=Q(plans__orders__status=Order.Status.PAID),
            distinct=True,
        ))
        .order_by("-paid_order_count", "-created_at")[:8]
    )

    seller_product_count_sq = (
        Product.objects.filter(seller_id=OuterRef("pk"), visibility=Product.Visibility.PUBLIC)
        .order_by()
        .values("seller_id")
        .annotate(cnt=Count("id"))
        .values("cnt")
    )
    featured_sellers = (
        SellerProfile.objects.filter(is_active=True, is_approved=True)
        .annotate(product_count=Coalesce(Subquery(seller_product_count_sq), 0))
        .filter(product_count__gt=0)
        .order_by("-product_count", "-created_at")[:8]
    )

    testimonials = (
        ProductReview.objects.filter(
            is_published=True,
            rating__gte=4,
            product__visibility=Product.Visibility.PUBLIC,
        )
        .select_related("product", "order__customer__user")
        .order_by("-created_at")[:6]
    )

    _emit_event(request, "page_view")
    return render(request, "storefront/landing.html", {
        "trending_products": trending_products,
        "featured_sellers": featured_sellers,
        "testimonials": testimonials,
    })


# ── Store page ────────────────────────────────────────────────────────────────

@xframe_options_sameorigin
def page(request, slug):
    """Public store page — a single seller's link-in-bio page at /<slug>/.

    Supports ?preview=1 to bypass is_published check when the authenticated
    user is the owner of the store (seller dashboard preview iframe).
    """
    is_preview = request.GET.get("preview") == "1"
    qs = StorePage.objects.select_related("seller")

    if is_preview and request.user.is_authenticated:
        store_page = get_object_or_404(qs, slug=slug)
        # Only the store owner may preview an unpublished store
        if not store_page.is_published:
            is_owner = (
                store_page.seller is not None
                and store_page.seller.user_id == request.user.pk
            )
            if not is_owner:
                raise Http404
    else:
        store_page = get_object_or_404(qs, slug=slug, is_published=True)

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

    _emit_event(request, "page_view")
    theme = store_page.theme if store_page else {}
    return render(request, "storefront/page.html", {
        "store_page": store_page,
        "blocks": blocks,
        "sold_counts": sold_counts,
        "theme": theme,
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
    reviews = product.reviews.filter(is_published=True).select_related("order__customer__user").order_by("-created_at")[:10]
    _emit_event(request, "product_view", product=product)

    # Capture affiliate ref code into session
    ref_code = request.GET.get("ref", "").strip()
    if ref_code:
        request.session["affiliate_ref"] = ref_code

    return render(request, "storefront/product.html", {
        "product": product,
        "plans": plans,
        "sold_count": sold_count,
        "reviews": reviews,
    })


# ── Checkout ──────────────────────────────────────────────────────────────────


def checkout_plan(request, plan_pk):
    plan = get_object_or_404(Plan, pk=plan_pk, is_active=True)
    product = plan.product

    if product.visibility == Product.Visibility.DRAFT:
        messages.error(request, "Product not available.")
        return redirect("storefront:page")

    # Guest Checkout interception on POST
    if not request.user.is_authenticated and request.method == "POST":
        email = request.POST.get("guest_email", "").strip().lower()
        if not email:
            messages.error(request, "Email is required to checkout.")
            return redirect(request.path)

        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address.")
            return redirect(request.path)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        if user:
            messages.info(request, "An account with this email exists. Please log in to complete your purchase.")
            from django.urls import reverse
            from urllib.parse import urlencode
            return redirect(f"{reverse('account_login')}?{urlencode({'next': request.path, 'login_hint': email})}")
        else:
            user = User.objects.create_user(email=email)
            user.set_unusable_password()
            user.save()
            from allauth.account.models import EmailAddress
            EmailAddress.objects.create(user=user, email=email, primary=True, verified=False)
            from allauth.account.utils import perform_login
            perform_login(request, user, email_verification="none")
            request.user = user

    if request.user.is_authenticated:
        customer, _ = _get_or_create_customer(request.user)
        wallet_balance = customer.wallet.balance
    else:
        customer = None
        wallet_balance = 0

    _SESSION_KEY = f"ck_token_{plan_pk}"

    questions = list(product.questions.all().order_by("sort_order"))

    if request.method == "GET":
        # Generate a stable idempotency token for this checkout intent.
        # Reusing the same token on POST prevents double-charge on double-click.
        checkout_token = uuid.uuid4().hex
        request.session[_SESSION_KEY] = checkout_token

        if request.user.is_authenticated:
            customer.wallet.refresh_from_db()
            wallet_balance = customer.wallet.balance
            try:
                from allauth.account.models import EmailAddress
                if not EmailAddress.objects.filter(user=request.user, verified=True).exists():
                    messages.warning(request, "Your email is not verified. Please verify it to ensure order notifications reach you.")
            except Exception:
                pass

        # Duration multiplier (recurring plans only)
        duration_multiplier = 1
        duration_discount_pct = 0
        duration_discount_amount = 0
        if plan.interval != 'none':
            try:
                duration_multiplier = max(1, int(request.GET.get("duration", 1)))
            except (ValueError, TypeError):
                duration_multiplier = 1
            duration_discount_pct = int(plan.duration_discounts.get(str(duration_multiplier), 0))

        # Coupon preview (GET ?coupon_code=XXX)
        from apps.billing.models import Coupon
        discount = 0
        coupon_obj = None
        coupon_error = None
        coupon_code_get = request.GET.get("coupon_code", "").strip().upper()

        # Base price after duration multiplier + duration discount
        base_price = plan.price
        if plan.interval != 'none' and duration_multiplier > 1:
            subtotal = base_price * duration_multiplier
            duration_discount_amount = subtotal * duration_discount_pct // 100
            base_price = subtotal - duration_discount_amount
        else:
            duration_discount_amount = 0

        if coupon_code_get:
            try:
                coupon_obj = Coupon.objects.get(code=coupon_code_get)
                valid, reason = coupon_obj.is_valid_for(plan)
                if valid:
                    discount = coupon_obj.compute_discount(base_price)
                else:
                    coupon_error = reason
                    coupon_obj = None
            except Coupon.DoesNotExist:
                coupon_error = "Coupon code not found."

        effective_price = max(0, base_price - discount)
        shortfall = max(0, effective_price - wallet_balance)
        balance_after = wallet_balance - effective_price if shortfall == 0 else 0

        master_direct_pay = Setting.get("DIRECT_PAY_ENABLED", "false").strip().lower() == "true"
        direct_pay_active = master_direct_pay and plan.direct_pay

        # Direct pay always charges the full amount via gateway; top-up-and-buy
        # only charges the shortfall. Payment methods are only needed when
        # some amount will actually be charged through the gateway.
        charge_amount = effective_price if direct_pay_active else shortfall
        payment_methods = _payment_methods(charge_amount) if charge_amount > 0 else []
        payment_method_groups = _group_payment_methods(payment_methods)

        _emit_event(request, "checkout_start", product=product, plan=plan)
        return render(request, "storefront/checkout.html", {
            "plan": plan,
            "product": product,
            "wallet_balance": wallet_balance,
            "shortfall": shortfall,
            "balance_after": balance_after,
            "checkout_token": checkout_token,
            "coupon": coupon_obj,
            "coupon_code": coupon_code_get,
            "coupon_error": coupon_error,
            "discount": discount,
            "effective_price": effective_price,
            "questions": questions,
            "payment_methods": payment_methods,
            "payment_method_groups": payment_method_groups,
            "duration_multiplier": duration_multiplier,
            "duration_discount_pct": duration_discount_pct,
            "duration_discount_amount": duration_discount_amount,
            "direct_pay_active": direct_pay_active,
        })

    # POST — run checkout
    from apps.billing.checkout import (
        checkout,
        CheckoutIdempotencyError,
        CouponLimitError,
        PaymentMethodRequiredError,
    )
    from apps.billing.models import Coupon

    checkout_token = request.POST.get("checkout_token") or request.session.get(_SESSION_KEY, uuid.uuid4().hex)
    checkout_key = f"ck:{request.user.pk}:{plan.pk}:{checkout_token}"
    return_url = request.build_absolute_uri("/orders/pending/")

    # Duration multiplier
    duration_multiplier = 1
    if plan.interval != 'none':
        try:
            duration_multiplier = max(1, int(request.POST.get("duration", 1)))
        except (ValueError, TypeError):
            duration_multiplier = 1

    # PWYW price override
    price_override = None
    if plan.pwyw:
        raw = request.POST.get("pwyw_price", "").strip()
        if raw:
            try:
                price_override = max(int(raw), plan.min_price or 0)
            except (ValueError, TypeError):
                price_override = plan.min_price or plan.price

    # Collect custom question answers
    custom_fields = {}
    for q in questions:
        key = f"q_{q.pk}"
        val = request.POST.get(key, "").strip()
        if q.required and not val:
            messages.error(request, f"Please answer: {q.label}")
            return redirect(request.path)
        custom_fields[str(q.pk)] = {"label": q.label, "value": val}

    # Stock check
    if plan.stock_quantity is not None:
        from apps.billing.models import Order as OrderModel
        sold = OrderModel.objects.filter(plan=plan, status=OrderModel.Status.PAID).count()
        if sold >= plan.stock_quantity:
            messages.error(request, "This item is out of stock.")
            return redirect("storefront:product", slug=product.slug)

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

    payment_method = request.POST.get("payment_method", "").strip() or None

    try:
        order, grants, payment_url = checkout(
            customer=customer,
            plan=plan,
            checkout_key=checkout_key,
            coupon=coupon,
            price_override=price_override,
            duration_multiplier=duration_multiplier,
            custom_fields=custom_fields,
            callback_url=_callback_url(request),
            return_url=return_url,
            payment_method=payment_method,
        )
    except CheckoutIdempotencyError:
        messages.error(request, "Duplicate checkout — please try again.")
        return redirect("storefront:product", slug=product.slug)
    except CouponLimitError:
        messages.error(request, "Coupon is no longer available — usage limit reached.")
        return redirect("storefront:checkout", plan_pk=plan.pk)
    except PaymentMethodRequiredError:
        messages.error(request, "Please choose a payment method.")
        return redirect("storefront:checkout", plan_pk=plan.pk)

    if payment_url:
        return redirect(payment_url)

    _emit_event(request, "order_paid", product=product, plan=plan)
    _record_affiliate_commission(request, order)
    return redirect("storefront:order_status", public_id=order.public_id)


# ── Order status ──────────────────────────────────────────────────────────────

def order_pending(request):
    """Duitku browser return URL after a payment attempt (topup/checkout).

    This is only the front-channel redirect — actual crediting happens
    asynchronously via the webhook (apps.billing.views.duitku_webhook). Route
    the buyer to the right status page rather than showing anything final here.
    """
    merchant_order_id = request.GET.get("merchantOrderId", "")
    topup_obj = (
        TopUp.objects.filter(public_id=merchant_order_id)
        .select_related("checkout_order")
        .first()
    )
    if topup_obj and topup_obj.checkout_order:
        return redirect("storefront:order_status", public_id=topup_obj.checkout_order.public_id)
    if topup_obj:
        messages.info(request, "Thanks! We're confirming your payment — your balance will update in a moment.")
        return redirect("dashboard:wallet")
    messages.error(request, "We couldn't find that transaction.")
    return redirect("storefront:page")


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
        payment_method = request.POST.get("payment_method", "").strip()

        if amount < MIN_TOPUP:
            messages.error(request, f"Minimum top-up is Rp{MIN_TOPUP:,}.")
        elif amount > MAX_TOPUP:
            messages.error(request, f"Maximum top-up is Rp{MAX_TOPUP:,}.")
        elif not payment_method:
            messages.error(request, "Please choose a payment method.")
        else:
            from apps.billing.services import initiate_topup

            try:
                bonus_pct = int(Setting.get("TOPUP_BONUS_PERCENT", "0"))
                bonus = amount * bonus_pct // 100
                topup_obj, payment_url = initiate_topup(
                    customer=customer,
                    amount=amount,
                    payment_method=payment_method,
                    bonus=bonus,
                    callback_url=_callback_url(request),
                    return_url=request.build_absolute_uri("/dashboard/wallet/"),
                )
                return redirect(payment_url)
            except Exception as exc:
                logger.error("topup initiation failed: %s", exc)
                messages.error(request, "Top-up unavailable right now. Please try again.")

    try:
        from allauth.account.models import EmailAddress
        if not EmailAddress.objects.filter(user=request.user, verified=True).exists():
            messages.warning(request, "Your email is not verified. Verify it to receive top-up receipts.")
    except Exception:
        pass

    try:
        prefill_amount = int(request.GET.get("amount", 0))
    except (ValueError, TypeError):
        prefill_amount = 0

    quick_amounts = [
        {"value": v, "label": f"{v:,}"}
        for v in [50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000]
    ]
    topup_payment_methods = _payment_methods(prefill_amount or MIN_TOPUP)
    return render(request, "storefront/topup.html", {
        "customer": customer,
        "wallet": customer.wallet,
        "quick_amounts": quick_amounts,
        "min_topup": MIN_TOPUP,
        "max_topup": MAX_TOPUP,
        "prefill_amount": prefill_amount,
        "payment_methods": topup_payment_methods,
        "payment_method_groups": _group_payment_methods(topup_payment_methods),
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


# ── Legal Pages ───────────────────────────────────────────────────────────────

def terms(request):
    return render(request, "storefront/terms.html")

def privacy(request):
    return render(request, "storefront/privacy.html")

