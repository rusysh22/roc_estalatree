"""Storefront views — public-facing product catalog, checkout, top-up.

Anonymous visitors can browse; checkout requires a logged-in Customer.
If a user has no Customer profile yet (e.g. fresh Google SSO), one is
created automatically before checkout proceeds.

Top-up-and-buy: if balance < plan price at checkout, a Sumopod payment
is initiated and the user is redirected to the payment page. On webhook
receipt the Order is fulfilled automatically (ADR-015).
"""
import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core import signing
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.accounts.models import SellerProfile
from apps.billing.models import Order, TopUp
from apps.catalog.models import Plan, Product, ProductReview
from apps.core.models import Setting
from apps.storefront.models import Block, StorePage

logger = logging.getLogger(__name__)

ORDER_RECEIPT_SALT = "order-receipt"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_customer(user):
    """Return (customer, created). Auto-creates Customer + wallet on first visit."""
    from apps.accounts.models import Customer
    customer, created = Customer.objects.get_or_create(user=user)
    if created:
        # Wallet is created by post_save signal in wallet/signals.py
        customer.refresh_from_db()
    return customer, created


# Sumopod sandbox supports QRIS only; other methods are shown as "under maintenance".
PAYMENT_METHOD = "QRIS"


def _callback_url(request):
    # Sumopod webhooks are configured in the dashboard, not per request. Kept for
    # backwards-compatible call signatures.
    return request.build_absolute_uri("/billing/webhook/sumopod/")


def build_order_receipt_token(order) -> str:
    """Long-lived signed token proving ownership of an order without a login session.

    Used on the confirmation email's "View order details" link — guest checkout
    accounts have an unusable password (apps/storefront/views.py:checkout_plan) so
    there's no reliable way for them to log back into the exact account later.
    No max_age is set on verification, so this token never expires (a receipt link
    should behave like a paid invoice PDF, not a security-sensitive action).
    """
    return signing.dumps({"public_id": order.public_id}, salt=ORDER_RECEIPT_SALT)


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


def search(request):
    """Marketplace-wide search by product name/description or seller name.

    Only surfaces PUBLIC products from active+approved sellers — same
    visibility rule as the landing page's trending/featured querysets.
    """
    query = request.GET.get("q", "").strip()
    results = []
    if query:
        results = (
            Product.objects.filter(
                visibility=Product.Visibility.PUBLIC,
                seller__is_active=True,
                seller__is_approved=True,
            )
            .filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(seller__name__icontains=query)
            )
            .select_related("seller")
            .prefetch_related(Prefetch(
                "plans", queryset=Plan.objects.filter(is_active=True).order_by("price")
            ))
            .distinct()
            .order_by("-created_at")
        )
    return render(request, "storefront/search_results.html", {
        "query": query,
        "results": results,
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
    plans = list(product.plans.filter(is_active=True).order_by("sort_order", "price"))
    sold_count = Order.objects.filter(
        plan__product=product, status=Order.Status.PAID
    ).count()
    reviews = product.reviews.filter(is_published=True).select_related("order__customer__user").order_by("-created_at")[:10]
    _emit_event(request, "product_view", product=product)

    # Capture affiliate ref code into session
    ref_code = request.GET.get("ref", "").strip()
    if ref_code:
        request.session["affiliate_ref"] = ref_code

    # Sticky mobile CTA: one plan → buy straight; many → "from <cheapest>".
    single_plan = plans[0] if len(plans) == 1 else None
    cheapest_price = min((p.price for p in plans), default=0)

    return render(request, "storefront/product.html", {
        "product": product,
        "plans": plans,
        "sold_count": sold_count,
        "reviews": reviews,
        "single_plan": single_plan,
        "cheapest_price": cheapest_price,
    })


def product_quotation_pdf(request, slug):
    """Downloadable price-quote PDF for a product's currently offered plans.

    No order/payment involved — reference-only pricing snapshot a visitor can
    save or forward (e.g. for internal budget approval before purchasing).
    """
    from apps.catalog.quotation_service import render_product_quotation_pdf

    product = get_object_or_404(
        Product, slug=slug,
        visibility__in=[Product.Visibility.PUBLIC, Product.Visibility.UNLISTED],
    )
    plans = product.plans.filter(is_active=True).order_by("sort_order", "price")

    pdf_bytes = render_product_quotation_pdf(product, plans)
    if pdf_bytes is None:
        raise Http404("Quotation could not be generated.")

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="quotation-{product.slug}.pdf"'
    return response


# ── Checkout ──────────────────────────────────────────────────────────────────


def _intercept_guest_checkout(request):
    """Promote an anonymous POSTer into a real (unverified) account from `guest_email`.

    Returns an HttpResponse to short-circuit with (missing/invalid email, or an
    existing account that must log in), or None when the guest was signed in and
    the caller should continue. On success `request.user` is set.
    """
    email = request.POST.get("guest_email", "").strip().lower()
    if not email:
        messages.error(request, "Email is required to checkout.")
        return redirect(request.get_full_path())

    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, "Please enter a valid email address.")
        return redirect(request.get_full_path())

    from django.contrib.auth import get_user_model
    User = get_user_model()
    if User.objects.filter(email__iexact=email).exists():
        from urllib.parse import urlencode
        messages.info(request, "An account with this email exists. Please log in to complete your purchase.")
        return redirect(f"{reverse('account_login')}?{urlencode({'next': request.path, 'login_hint': email})}")

    user = User.objects.create_user(email=email)
    user.set_unusable_password()
    user.save()
    from allauth.account.models import EmailAddress
    EmailAddress.objects.create(user=user, email=email, primary=True, verified=False)
    from allauth.account.utils import perform_login
    perform_login(request, user, email_verification="none")
    request.user = user
    return None


def checkout_plan(request, plan_pk):
    plan = get_object_or_404(Plan, pk=plan_pk, is_active=True)
    product = plan.product

    if product.visibility == Product.Visibility.DRAFT:
        messages.error(request, "Product not available.")
        return redirect("storefront:page")

    # Captured before the guest-signup block below flips this to True — an
    # already-logged-in buyer's unverified email gets checked before any
    # payment-gateway charge (see PaymentMethodRequiredError handling further
    # down); a brand-new guest signup can't verify mid-checkout so is exempt.
    was_already_authenticated = request.user.is_authenticated

    # Guest Checkout interception on POST
    if not request.user.is_authenticated and request.method == "POST":
        guest_redirect = _intercept_guest_checkout(request)
        if guest_redirect is not None:
            return guest_redirect

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
        # only charges the shortfall.
        charge_amount = effective_price if direct_pay_active else shortfall
        # Fee passthrough: the customer pays charge_amount + gateway fee at Sumopod.
        from apps.billing.sumopod import estimate_fee, is_configured
        gateway_online = is_configured()
        gateway_charge = charge_amount > 0 and gateway_online
        gateway_unavailable = charge_amount > 0 and not gateway_online
        gateway_fee = estimate_fee(charge_amount) if gateway_charge else 0
        gateway_total = charge_amount + gateway_fee

        seller = getattr(product, "seller", None)
        qris_seller = seller if seller and seller.qris_ready else None

        # Which method is pre-selected, and the amount shown on the sticky CTA.
        wallet_covers = not direct_pay_active and shortfall == 0 and effective_price > 0
        no_payment_method = (
            effective_price > 0 and not wallet_covers and not gateway_charge and not qris_seller
        )
        subtotal_amount = plan.price * duration_multiplier if duration_multiplier > 1 else plan.price
        if effective_price == 0:
            checkout_total, checkout_btn_label = 0, "Confirm order"
        elif wallet_covers:
            checkout_total, checkout_btn_label = effective_price, "Confirm & pay"
        elif gateway_charge:
            checkout_total, checkout_btn_label = gateway_total, "Pay now"
        elif qris_seller:
            checkout_total, checkout_btn_label = effective_price, "Place order"
        else:  # nothing available right now
            checkout_total, checkout_btn_label = effective_price, "Payment unavailable"

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
            "subtotal_amount": subtotal_amount,
            "questions": questions,
            "gateway_charge": gateway_charge,
            "gateway_charge_amount": charge_amount,
            "gateway_fee": gateway_fee,
            "gateway_total": gateway_total,
            "gateway_unavailable": gateway_unavailable,
            "no_payment_method": no_payment_method,
            "duration_multiplier": duration_multiplier,
            "duration_discount_pct": duration_discount_pct,
            "duration_discount_amount": duration_discount_amount,
            "direct_pay_active": direct_pay_active,
            "qris_seller": qris_seller,
            "wallet_covers": wallet_covers,
            "checkout_total": checkout_total,
            "checkout_btn_label": checkout_btn_label,
        })

    # POST — run checkout
    from apps.billing.checkout import (
        checkout,
        CheckoutIdempotencyError,
        CouponLimitError,
        PaymentMethodRequiredError,
        QrisNotAvailableError,
    )
    from apps.billing.sumopod import SumopodError
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
    is_qris_static = payment_method == "qris_static"
    payment_proof = request.FILES.get("payment_proof") if is_qris_static else None

    if payment_method and not is_qris_static and was_already_authenticated:
        from allauth.account.models import EmailAddress
        if not EmailAddress.objects.filter(user=request.user, verified=True).exists():
            messages.error(request, "Please verify your email before paying via a payment method — this protects your order confirmation and license delivery.")
            return redirect("account_email")

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
            payment_proof=payment_proof,
        )
    except QrisNotAvailableError:
        messages.error(request, "Static QRIS is not available for this product.")
        return redirect("storefront:checkout", plan_pk=plan.pk)
    except CheckoutIdempotencyError:
        messages.error(request, "Duplicate checkout — please try again.")
        return redirect("storefront:product", slug=product.slug)
    except CouponLimitError:
        messages.error(request, "Coupon is no longer available — usage limit reached.")
        return redirect("storefront:checkout", plan_pk=plan.pk)
    except PaymentMethodRequiredError:
        messages.error(request, "Please choose a payment method.")
        return redirect("storefront:checkout", plan_pk=plan.pk)
    except SumopodError as exc:
        logger.error("Sumopod payment initiation failed at checkout: %s", exc)
        messages.error(request, "Online payment is unavailable right now — please try again in a moment.")
        return redirect("storefront:checkout", plan_pk=plan.pk)

    if payment_url:
        return redirect(payment_url)

    if order.status == order.Status.PAID:
        _emit_event(request, "order_paid", product=product, plan=plan)
        _record_affiliate_commission(request, order)
    elif is_qris_static:
        messages.info(request, "Order placed. Complete the QRIS payment — the seller will confirm it shortly.")
    return redirect("storefront:order_status", public_id=order.public_id)


# ── Order status ──────────────────────────────────────────────────────────────

def order_pending(request):
    """Sumopod browser return URL after a payment attempt (topup/checkout).

    This is only the front-channel redirect — actual crediting happens
    asynchronously via the webhook (apps.billing.views.sumopod_webhook). Route
    the buyer to the right status page rather than showing anything final here.
    """
    # `ref` is set by our success_return_url; `merchantOrderId` is the legacy param.
    ref = request.GET.get("ref") or request.GET.get("merchantOrderId", "")
    topup_qs = TopUp.objects.select_related("checkout_order", "cart_checkout")
    topup_obj = None
    if ref:
        topup_obj = topup_qs.filter(public_id=ref).first()
    if topup_obj is None and request.user.is_authenticated:
        # Fall back to this customer's most recent top-up (Sumopod may not echo params).
        topup_obj = (
            topup_qs.filter(customer__user=request.user).order_by("-created_at").first()
        )
    if topup_obj and topup_obj.checkout_order:
        return redirect("storefront:order_status", public_id=topup_obj.checkout_order.public_id)
    if topup_obj and topup_obj.cart_checkout_id:
        return redirect("storefront:cart_checkout_receipt", public_id=topup_obj.cart_checkout.public_id)
    if topup_obj:
        messages.info(request, "Thanks! We're confirming your payment — your balance will update in a moment.")
        return redirect("dashboard:wallet")
    messages.error(request, "We couldn't find that transaction.")
    return redirect("storefront:page")


def _resolve_receipt_order(request, public_id):
    """Return (order, token) for a receipt view — owner session OR signed ?token=.

    Returns (None, "") when neither grants access (caller redirects to login).
    """
    token = request.GET.get("token", "")
    if token:
        try:
            data = signing.loads(token, salt=ORDER_RECEIPT_SALT)
        except signing.BadSignature:
            data = None
        if data and data.get("public_id") == public_id:
            return get_object_or_404(
                Order.objects.select_related(
                    "plan__product__seller", "customer__user", "coupon", "subscription"
                ),
                public_id=public_id,
            ), token

    if request.user.is_authenticated:
        customer, _ = _get_or_create_customer(request.user)
        return get_object_or_404(
            Order.objects.select_related(
                "plan__product__seller", "customer__user", "coupon", "subscription"
            ),
            public_id=public_id,
            customer=customer,
        ), ""

    return None, ""


def order_status(request, public_id):
    """Order receipt page — reachable either by an owner's login session, or by a
    long-lived signed ?token= (see build_order_receipt_token) so the confirmation
    email link works even when the visitor's guest session is long gone.
    """
    order, token = _resolve_receipt_order(request, public_id)
    if order is None:
        return redirect_to_login(request.get_full_path(), reverse("account_login"))

    grants = []
    if order.status == Order.Status.PAID:
        from apps.provisioning.models import Grant
        grants = list(Grant.objects.filter(order=order))

    dm = order.duration_multiplier or 1
    subtotal = order.plan.price * dm
    duration_discount_pct = int(order.plan.duration_discounts.get(str(dm), 0)) if dm > 1 else 0
    duration_discount_amount = subtotal * duration_discount_pct // 100 if duration_discount_pct else 0

    return render(request, "storefront/order_status.html", {
        "order": order,
        "customer": order.customer,
        "grants": grants,
        "receipt_token": token,
        "dm": dm,
        "subtotal": subtotal,
        "duration_discount_pct": duration_discount_pct,
        "duration_discount_amount": duration_discount_amount,
    })


def qris_download(request, slug):
    """Serve a seller's static QRIS as a fresh PNG (scannable, universally openable).

    The stored file may be WebP (photo pipeline) or PNG — this always hands the
    buyer a PNG named after the store, so it saves cleanly to a phone gallery.
    """
    seller = get_object_or_404(SellerProfile, slug=slug)
    if not seller.qris_ready:
        raise Http404("No QRIS available.")

    from io import BytesIO

    from django.utils.text import slugify
    from PIL import Image

    try:
        seller.qris_image.open("rb")
        img = Image.open(seller.qris_image).convert("RGB")
        seller.qris_image.close()
    except Exception:
        logger.exception("qris_download: cannot read QRIS for seller %s", seller.pk)
        raise Http404("QRIS image is unavailable.")

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    response = HttpResponse(buf.getvalue(), content_type="image/png")
    response["Content-Disposition"] = f'attachment; filename="QRIS-{slugify(seller.name) or seller.slug}.png"'
    return response


def order_invoice_pdf(request, public_id):
    """Download the paid invoice as PDF — same access rules as the receipt page."""
    order, _token = _resolve_receipt_order(request, public_id)
    if order is None:
        return redirect_to_login(request.get_full_path(), reverse("account_login"))
    if order.status != Order.Status.PAID:
        raise Http404("Invoice is only available once the order is paid.")

    from apps.billing.invoice_service import render_invoice_pdf

    pdf_bytes = render_invoice_pdf(order)
    if not pdf_bytes:
        raise Http404("Could not generate the invoice PDF.")
    label = f"INV-{order.invoice_number:06d}" if order.invoice_number else order.public_id
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{label}.pdf"'
    return response


# ── Top-up ────────────────────────────────────────────────────────────────────

@login_required
def topup(request):
    customer, _ = _get_or_create_customer(request.user)
    customer.wallet.refresh_from_db()

    MIN_TOPUP = int(Setting.get("MIN_TOPUP", "10000"))
    MAX_TOPUP = int(Setting.get("MAX_TOPUP", "50000000"))

    if request.method == "POST":
        from allauth.account.models import EmailAddress
        if not EmailAddress.objects.filter(user=request.user, verified=True).exists():
            messages.error(request, "Please verify your email before topping up — this protects your balance and receipts.")
            return redirect("account_email")

        try:
            amount = int(request.POST.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0
        payment_method = request.POST.get("payment_method", "").strip() or PAYMENT_METHOD

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
    from apps.billing.sumopod import FEE_FLAT, FEE_PERCENT
    return render(request, "storefront/topup.html", {
        "customer": customer,
        "wallet": customer.wallet,
        "quick_amounts": quick_amounts,
        "min_topup": MIN_TOPUP,
        "max_topup": MAX_TOPUP,
        "prefill_amount": prefill_amount,
        "fee_percent": FEE_PERCENT,
        "fee_flat": FEE_FLAT,
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


# ── Cart (docs/feedback item #12) ───────────────────────────────────────────────
# v1 scope: a cart can hold plans from multiple sellers (checked out with one
# combined payment — see apps.billing.cart_service). Anonymous visitors can add
# to a session-bound cart; checkout itself requires login (matches top-up).
# PWYW plans and plans with required intake questions are not addable to cart.

def _cart_lines(cart, only_ids=None):
    from apps.billing.cart_service import compute_cart_line

    lines, total = [], 0
    wanted = {int(i) for i in only_ids} if only_ids is not None else None
    for item in cart.items.select_related("plan__product__seller").all():
        if wanted is not None and item.pk not in wanted:
            continue
        price, discount, coupon_obj, base_price = compute_cart_line(item)
        lines.append({"item": item, "price": price, "discount": discount,
                      "coupon": coupon_obj, "base_price": base_price})
        total += price
    return lines, total


def _cart_ajax_response(request, cart, *, status=200):
    """JSON payload the cart drawer JS expects: live count + freshly rendered drawer."""
    lines, total = _cart_lines(cart)
    html = render(request, "storefront/partials/_cart_drawer.html",
                  {"lines": lines, "total": total}).content.decode()
    return JsonResponse({"count": len(lines), "total": total, "html": html}, status=status)


def cart_view(request):
    from apps.billing.cart_service import get_or_create_cart

    cart = get_or_create_cart(request)
    lines, total = _cart_lines(cart)
    return render(request, "storefront/cart.html", {"lines": lines, "total": total})


def cart_drawer(request):
    """Slide-over cart contents. JSON for cart.js, plain partial as a fallback."""
    from apps.billing.cart_service import get_or_create_cart

    cart = get_or_create_cart(request)
    if request.headers.get("X-Requested-With") == "fetch":
        return _cart_ajax_response(request, cart)
    lines, total = _cart_lines(cart)
    return render(request, "storefront/partials/_cart_drawer.html", {"lines": lines, "total": total})


@require_POST
def cart_add(request, plan_pk):
    from apps.billing.cart_service import CartError, add_to_cart, get_or_create_cart

    plan = get_object_or_404(Plan, pk=plan_pk, is_active=True)
    cart = get_or_create_cart(request)
    ajax = request.headers.get("X-Requested-With") == "fetch"
    try:
        duration_multiplier = int(request.POST.get("duration", 1))
    except (TypeError, ValueError):
        duration_multiplier = 1

    try:
        add_to_cart(cart, plan, duration_multiplier=duration_multiplier)
    except CartError as exc:
        if ajax:
            return JsonResponse({"error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect("storefront:product", slug=plan.product.slug)

    if ajax:
        return _cart_ajax_response(request, cart)
    messages.success(request, f"Added '{plan.product.name}' to your cart.")
    return redirect("storefront:cart")


@require_POST
def cart_remove(request, item_pk):
    from apps.billing.cart_service import get_or_create_cart, remove_from_cart

    cart = get_or_create_cart(request)
    remove_from_cart(cart, item_pk)
    if request.headers.get("X-Requested-With") == "fetch":
        return _cart_ajax_response(request, cart)
    messages.info(request, "Removed from cart.")
    return redirect("storefront:cart")


@require_POST
def cart_update(request, item_pk):
    from apps.billing.cart_service import get_or_create_cart, update_cart_item

    cart = get_or_create_cart(request)
    try:
        duration_multiplier = int(request.POST.get("duration", 1))
    except (TypeError, ValueError):
        duration_multiplier = 1
    update_cart_item(cart, item_pk, duration_multiplier=duration_multiplier)
    if request.headers.get("X-Requested-With") == "fetch":
        return _cart_ajax_response(request, cart)
    return redirect("storefront:cart")


def cart_checkout_view(request):
    from apps.billing.sumopod import SumopodError, estimate_fee
    from apps.billing.cart_service import (
        CartError,
        CartPaymentMethodRequiredError,
        EmptyCartError,
        checkout_cart,
        get_or_create_cart,
    )

    was_already_authenticated = request.user.is_authenticated

    # Guest checkout: promote from `guest_email` on POST, then re-resolve the cart
    # (this merges the session cart into the new customer's cart).
    if not request.user.is_authenticated and request.method == "POST":
        guest_redirect = _intercept_guest_checkout(request)
        if guest_redirect is not None:
            return guest_redirect

    cart = get_or_create_cart(request)

    # A subset of the cart may be selected on the cart page (checkbox per line).
    selected_ids = request.POST.getlist("item") or request.GET.getlist("item") or None
    all_ids = list(cart.items.values_list("pk", flat=True))
    if selected_ids is not None:
        selected_ids = [i for i in selected_ids if i.isdigit() and int(i) in all_ids]
    lines, total = _cart_lines(cart, only_ids=selected_ids)
    if not lines:
        messages.info(request, "Your cart is empty.")
        return redirect("storefront:cart")

    if request.user.is_authenticated:
        customer, _ = _get_or_create_customer(request.user)
        wallet_balance = customer.wallet.balance
    else:
        customer, wallet_balance = None, 0

    shortfall = max(0, total - wallet_balance)
    seller_ids = {ln["item"].plan.product.seller_id for ln in lines}
    single_seller = lines[0]["item"].plan.product.seller if len(seller_ids) == 1 else None
    qris_seller = single_seller if single_seller and single_seller.qris_ready else None

    if request.method == "GET":
        if request.user.is_authenticated and shortfall > 0:
            from allauth.account.models import EmailAddress
            if not EmailAddress.objects.filter(user=request.user, verified=True).exists():
                messages.warning(request, "Your email is not verified. Please verify it to ensure order notifications reach you.")

        from apps.billing.sumopod import is_configured
        gateway_online = is_configured()
        gateway_fee = estimate_fee(shortfall) if shortfall > 0 and gateway_online else 0
        wallet_covers = request.user.is_authenticated and shortfall == 0
        return render(request, "storefront/cart_checkout.html", {
            "lines": lines,
            "total": total,
            "selected_ids": selected_ids or [ln["item"].pk for ln in lines],
            "wallet_balance": wallet_balance,
            "wallet_covers": wallet_covers,
            "shortfall": shortfall if gateway_online else 0,
            "gateway_fee": gateway_fee,
            "gateway_charge_amount": shortfall,
            "gateway_total": shortfall + gateway_fee,
            "gateway_unavailable": shortfall > 0 and not gateway_online,
            "no_payment_method": shortfall > 0 and not gateway_online and not qris_seller and not wallet_covers,
            "qris_seller": qris_seller,
        })

    payment_method = request.POST.get("payment_method", "").strip() or None
    is_qris_static = payment_method == "qris_static"
    payment_proof = request.FILES.get("payment_proof") if is_qris_static else None

    if payment_method and not is_qris_static and shortfall > 0 and was_already_authenticated:
        from allauth.account.models import EmailAddress
        if not EmailAddress.objects.filter(user=request.user, verified=True).exists():
            messages.error(request, "Please verify your email before paying via a payment method.")
            return redirect("account_email")

    try:
        cart_checkout, grants, payment_url = checkout_cart(
            customer=customer,
            cart=cart,
            callback_url=_callback_url(request),
            return_url=request.build_absolute_uri("/orders/pending/"),
            payment_method=payment_method,
            payment_proof=payment_proof,
            selected_item_ids=selected_ids,
        )
    except CartPaymentMethodRequiredError:
        messages.error(request, "Please choose a payment method.")
        return redirect("storefront:cart_checkout")
    except EmptyCartError:
        messages.info(request, "Your cart is empty.")
        return redirect("storefront:cart")
    except SumopodError as exc:
        logger.error("Sumopod payment initiation failed at cart checkout: %s", exc)
        messages.error(request, "Online payment is unavailable right now — your cart is saved, please try again in a moment.")
        return redirect("storefront:cart_checkout")
    except CartError as exc:
        messages.error(request, str(exc))
        return redirect("storefront:cart_checkout")

    if payment_url:
        return redirect(payment_url)

    return redirect("storefront:cart_checkout_receipt", public_id=cart_checkout.public_id)


@login_required
def cart_checkout_receipt(request, public_id):
    from apps.billing.models import CartCheckout

    customer, _ = _get_or_create_customer(request.user)
    cart_checkout = get_object_or_404(CartCheckout, public_id=public_id, customer=customer)
    orders = list(
        cart_checkout.orders
        .select_related("plan__product__seller", "subscription")
        .prefetch_related("grants")
        .order_by("plan__product__seller__name", "created_at")
    )

    # Group by store so a multi-seller cart reads clearly.
    stores = []
    for order in orders:
        seller = order.plan.product.seller
        key = seller.pk if seller else 0
        if not stores or stores[-1]["key"] != key:
            stores.append({"key": key, "seller": seller, "orders": [], "subtotal": 0})
        stores[-1]["orders"].append(order)
        stores[-1]["subtotal"] += order.amount

    return render(request, "storefront/cart_checkout_receipt.html", {
        "cart_checkout": cart_checkout,
        "orders": orders,
        "stores": stores,
        "multi_store": len(stores) > 1,
        "total": sum(o.amount for o in orders),
    })

