"""Seller Dashboard views — Lynk.id-style creator interface at /seller/."""
import json
from django.contrib import messages
from django.db.models import Count, F, Sum, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Customer, SellerProfile
from apps.billing.models import AffiliateLink, Coupon, Order, SellerEarning, SellerPayout, Subscription
from apps.catalog.models import CourseLesson, CourseModule, Plan, Product, ProductQuestion
from apps.notifications.tasks import deliver_whatsapp
from apps.provisioning.models import Deliverable
from apps.storefront.models import Block, StorePage

from .decorators import seller_required
from .forms import (
    AffiliateLinkForm,
    BlockOrderForm,
    BroadcastForm,
    CouponForm,
    CourseLessonForm,
    CourseModuleForm,
    DeliverableForm,
    EntitlementForm,
    OnboardingProductForm,
    PayoutRequestForm,
    PlanForm,
    ProductForm,
    ProductQuestionForm,
    SellerProfileForm,
    StorePageForm,
    ThemeForm,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seller_products(seller):
    """All products belonging to this seller (null seller = platform default)."""
    if seller.user and seller.user.is_superuser:
        # Superuser sees all products (single-merchant mode)
        return Product.objects.all()
    return Product.objects.filter(seller=seller)


def _seller_orders(seller):
    """All orders for this seller's products."""
    products = _seller_products(seller)
    return Order.objects.filter(plan__product__in=products).select_related(
        "customer__user", "plan__product"
    )


# ── Dashboard home ────────────────────────────────────────────────────────────

@seller_required
def home(request):
    seller = request.seller

    orders_qs = _seller_orders(seller)
    revenue = orders_qs.filter(status=Order.Status.PAID).aggregate(
        total=Sum("amount")
    )["total"] or 0
    orders_count = orders_qs.filter(status=Order.Status.PAID).count()
    active_subs = Subscription.objects.filter(
        plan__product__in=_seller_products(seller),
        status=Subscription.Status.ACTIVE,
    ).count()
    pending_orders = orders_qs.filter(status=Order.Status.PENDING).count()
    recent_orders = orders_qs.order_by("-created_at")[:8]
    products_count = _seller_products(seller).count()

    # 7-day revenue chart data
    from django.db.models.functions import TruncDate
    today = timezone.now().date()
    week_ago = today - timezone.timedelta(days=6)
    daily_qs = (
        orders_qs
        .filter(status=Order.Status.PAID, created_at__date__gte=week_ago)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Sum("amount"))
        .order_by("day")
    )
    daily_map = {row["day"]: row["total"] for row in daily_qs}
    chart_days = []
    for i in range(7):
        d = week_ago + timezone.timedelta(days=i)
        chart_days.append({"date": d, "label": d.strftime("%d/%m"), "total": daily_map.get(d, 0)})
    chart_max = max((d["total"] for d in chart_days), default=1) or 1
    week_total = sum(d["total"] for d in chart_days)

    return render(request, "seller/home.html", {
        "seller": seller,
        "revenue": revenue,
        "orders_count": orders_count,
        "active_subs": active_subs,
        "pending_orders": pending_orders,
        "recent_orders": recent_orders,
        "products_count": products_count,
        "chart_days": chart_days,
        "chart_max": chart_max,
        "week_total": week_total,
    })


# ── Products ──────────────────────────────────────────────────────────────────

@seller_required
def products(request):
    seller = request.seller
    product_list = _seller_products(seller).prefetch_related("plans").order_by("name")

    # Per-product stats: paid order count + revenue
    product_pks = list(product_list.values_list("pk", flat=True))
    stats_qs = (
        Order.objects.filter(plan__product_id__in=product_pks, status=Order.Status.PAID)
        .values("plan__product_id")
        .annotate(orders=Count("id"), revenue=Sum("amount"))
    )
    product_stats = {
        row["plan__product_id"]: {"orders": row["orders"], "revenue": row["revenue"]}
        for row in stats_qs
    }

    return render(request, "seller/products.html", {
        "seller": seller,
        "products": product_list,
        "product_stats": product_stats,
    })


@seller_required
def product_create(request):
    seller = request.seller
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.seller = seller if not seller.user.is_superuser else None
            if not product.slug:
                product.slug = slugify(product.name)
            product.save()
            messages.success(request, f"Product '{product.name}' created.")
            return redirect("seller:product_edit", pk=product.pk)
    else:
        form = ProductForm()
    return render(request, "seller/product_form.html", {
        "seller": seller,
        "form": form,
        "title": "New Product",
        "submit_label": "Create Product",
    })


@seller_required
def product_edit(request, pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=pk)
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, "Product updated.")
            return redirect("seller:product_edit", pk=product.pk)
    else:
        form = ProductForm(instance=product)

    plans = product.plans.all()
    deliverables = Deliverable.objects.filter(plan__product=product).select_related("plan")
    questions = product.questions.all()
    return render(request, "seller/product_form.html", {
        "seller": seller,
        "form": form,
        "product": product,
        "plans": plans,
        "deliverables": deliverables,
        "questions": questions,
        "question_form": ProductQuestionForm(),
        "title": f"Edit — {product.name}",
        "submit_label": "Save Changes",
    })


@seller_required
def product_delete(request, pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=pk)
    if request.method == "POST":
        name = product.name
        product.visibility = Product.Visibility.DRAFT
        product.save(update_fields=["visibility", "updated_at"])
        messages.success(request, f"'{name}' moved to Draft (hidden from store).")
        return redirect("seller:products")
    return render(request, "seller/product_confirm_delete.html", {
        "seller": seller,
        "product": product,
    })


# ── Plans ─────────────────────────────────────────────────────────────────────

@seller_required
def plan_create(request, product_pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    if request.method == "POST":
        form = PlanForm(request.POST)
        deliverable_form = DeliverableForm(request.POST, prefix="dlv")
        if form.is_valid() and deliverable_form.is_valid():
            plan = form.save(commit=False)
            plan.product = product
            plan.save()
            deliverable = deliverable_form.save(commit=False)
            deliverable.plan = plan
            deliverable.save()
            messages.success(request, f"Plan '{plan.name}' created.")
            return redirect("seller:product_edit", pk=product.pk)
    else:
        form = PlanForm()
        deliverable_form = DeliverableForm(prefix="dlv")
    return render(request, "seller/plan_form.html", {
        "seller": seller,
        "product": product,
        "form": form,
        "deliverable_form": deliverable_form,
        "title": f"New Plan — {product.name}",
        "submit_label": "Create Plan",
    })


@seller_required
def plan_edit(request, product_pk, plan_pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    plan = get_object_or_404(Plan, pk=plan_pk, product=product)
    deliverable = Deliverable.objects.filter(plan=plan).first()
    if request.method == "POST":
        form = PlanForm(request.POST, instance=plan)
        deliverable_form = DeliverableForm(request.POST, instance=deliverable, prefix="dlv")
        if form.is_valid() and deliverable_form.is_valid():
            form.save()
            dlv = deliverable_form.save(commit=False)
            dlv.plan = plan
            dlv.save()
            messages.success(request, "Plan updated.")
            return redirect("seller:product_edit", pk=product.pk)
    else:
        form = PlanForm(instance=plan)
        deliverable_form = DeliverableForm(instance=deliverable, prefix="dlv")
    entitlements = plan.entitlements.all()
    return render(request, "seller/plan_form.html", {
        "seller": seller,
        "product": product,
        "plan": plan,
        "form": form,
        "deliverable_form": deliverable_form,
        "entitlements": entitlements,
        "entitlement_form": EntitlementForm(),
        "title": f"Edit Plan — {plan.name}",
        "submit_label": "Save Plan",
    })


@seller_required
@require_POST
def entitlement_add(request, product_pk, plan_pk):
    from apps.provisioning.models import Entitlement
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    plan = get_object_or_404(Plan, pk=plan_pk, product=product)
    form = EntitlementForm(request.POST)
    if form.is_valid():
        key = form.cleaned_data["key"].upper().strip()
        ent = Entitlement.objects.filter(key=key).first()
        if ent is None:
            ent = Entitlement.objects.create(
                key=key,
                name=form.cleaned_data["name"],
                value=form.cleaned_data["value"],
            )
        plan.entitlements.add(ent)
        messages.success(request, f"Entitlement '{key}' added to plan.")
    else:
        messages.error(request, "Invalid entitlement — key is required.")
    return redirect("seller:plan_edit", product_pk=product.pk, plan_pk=plan.pk)


@seller_required
@require_POST
def entitlement_remove(request, product_pk, plan_pk, ent_pk):
    from apps.provisioning.models import Entitlement
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    plan = get_object_or_404(Plan, pk=plan_pk, product=product)
    ent = get_object_or_404(Entitlement, pk=ent_pk)
    plan.entitlements.remove(ent)
    messages.success(request, f"Entitlement '{ent.key}' removed.")
    return redirect("seller:plan_edit", product_pk=product.pk, plan_pk=plan.pk)


# ── Product Questions ─────────────────────────────────────────────────────────

@seller_required
@require_POST
def question_add(request, product_pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    form = ProductQuestionForm(request.POST)
    if form.is_valid():
        q = form.save(commit=False)
        q.product = product
        q.save()
        messages.success(request, "Question added.")
    else:
        messages.error(request, "Invalid question — label is required.")
    return redirect("seller:product_edit", pk=product.pk)


@seller_required
@require_POST
def question_remove(request, product_pk, question_pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    q = get_object_or_404(ProductQuestion, pk=question_pk, product=product)
    q.delete()
    messages.success(request, "Question removed.")
    return redirect("seller:product_edit", pk=product.pk)


# ── Course Content Management ─────────────────────────────────────────────────

@seller_required
def course_modules(request, product_pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    modules = product.modules.prefetch_related("lessons").order_by("sort_order")

    if request.method == "POST":
        form = CourseModuleForm(request.POST)
        if form.is_valid():
            m = form.save(commit=False)
            m.product = product
            m.save()
            messages.success(request, "Module added.")
            return redirect("seller:course_modules", product_pk=product.pk)
    else:
        form = CourseModuleForm()

    return render(request, "seller/course_modules.html", {
        "seller": seller,
        "product": product,
        "modules": modules,
        "module_form": form,
        "lesson_form": CourseLessonForm(),
    })


@seller_required
@require_POST
def lesson_add(request, product_pk, module_pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    module = get_object_or_404(CourseModule, pk=module_pk, product=product)
    form = CourseLessonForm(request.POST)
    if form.is_valid():
        lesson = form.save(commit=False)
        lesson.module = module
        lesson.save()
        messages.success(request, "Lesson added.")
    else:
        messages.error(request, "Invalid lesson — title is required.")
    return redirect("seller:course_modules", product_pk=product.pk)


@seller_required
@require_POST
def module_delete(request, product_pk, module_pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    module = get_object_or_404(CourseModule, pk=module_pk, product=product)
    module.delete()
    messages.success(request, "Module deleted.")
    return redirect("seller:course_modules", product_pk=product.pk)


@seller_required
@require_POST
def lesson_delete(request, product_pk, module_pk, lesson_pk):
    seller = request.seller
    product = get_object_or_404(_seller_products(seller), pk=product_pk)
    module = get_object_or_404(CourseModule, pk=module_pk, product=product)
    lesson = get_object_or_404(CourseLesson, pk=lesson_pk, module=module)
    lesson.delete()
    messages.success(request, "Lesson deleted.")
    return redirect("seller:course_modules", product_pk=product.pk)


# ── Orders ────────────────────────────────────────────────────────────────────

@seller_required
def orders(request):
    seller = request.seller
    status_filter = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()

    qs = _seller_orders(seller).select_related(
        "customer__user", "plan__product", "subscription", "coupon"
    ).order_by("-created_at")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if search:
        qs = qs.filter(
            Q(customer__user__email__icontains=search)
            | Q(plan__product__name__icontains=search)
            | Q(plan__name__icontains=search)
        )

    all_orders = _seller_orders(seller)
    stats = {
        "paid": all_orders.filter(status=Order.Status.PAID).count(),
        "revenue": all_orders.filter(status=Order.Status.PAID).aggregate(t=Sum("amount"))["t"] or 0,
        "pending": all_orders.filter(status=Order.Status.PENDING).count(),
        "refunded": all_orders.filter(status=Order.Status.REFUNDED).count(),
    }

    return render(request, "seller/orders.html", {
        "seller": seller,
        "orders": qs[:200],
        "status_filter": status_filter,
        "search": search,
        "status_choices": Order.Status.choices,
        "stats": stats,
    })


@seller_required
def order_detail(request, pk):
    seller = request.seller
    order = get_object_or_404(
        Order.objects.select_related(
            "customer__user", "plan__product", "coupon", "subscription"
        ),
        pk=pk,
        plan__product__in=_seller_products(seller),
    )

    dm = order.duration_multiplier
    subtotal = order.plan.price * dm
    if dm > 1:
        disc_pct = int(order.plan.duration_discounts.get(str(dm), 0))
        duration_discount_amount = subtotal * disc_pct // 100
    else:
        disc_pct = 0
        duration_discount_amount = 0

    try:
        wallet_balance = order.customer.wallet.balance
    except Exception:
        wallet_balance = None

    return render(request, "seller/order_detail.html", {
        "seller": seller,
        "order": order,
        "subtotal": subtotal,
        "dm": dm,
        "duration_discount_pct": disc_pct,
        "duration_discount_amount": duration_discount_amount,
        "wallet_balance": wallet_balance,
    })


def _seller_manual_order(seller, pk):
    """A Static QRIS order belonging to this seller and still awaiting confirmation."""
    order = get_object_or_404(
        Order.objects.select_related("plan__product", "customer", "cart_checkout"),
        pk=pk,
        plan__product__in=_seller_products(seller),
    )
    if not order.awaiting_seller_confirmation:
        raise Http404("Order is not awaiting payment confirmation.")
    return order


@seller_required
@require_POST
def order_confirm_payment(request, pk):
    from apps.billing.checkout import confirm_cart_manual_payment, confirm_manual_payment

    order = _seller_manual_order(request.seller, pk)
    if order.cart_checkout_id:
        confirm_cart_manual_payment(order.cart_checkout)
    else:
        confirm_manual_payment(order)
    messages.success(request, "Payment confirmed — the order has been fulfilled.")
    return redirect("seller:order_detail", pk=pk)


@seller_required
@require_POST
def order_reject_payment(request, pk):
    from apps.billing.checkout import reject_manual_payment

    order = _seller_manual_order(request.seller, pk)
    reason = request.POST.get("reason", "").strip()
    if order.cart_checkout_id:
        for line in order.cart_checkout.orders.filter(status=Order.Status.PENDING):
            reject_manual_payment(line, reason=reason)
    else:
        reject_manual_payment(order, reason=reason)
    messages.info(request, "Payment marked as not received. The order was cancelled.")
    return redirect("seller:order_detail", pk=pk)


# ── Store (StorePage editor) ──────────────────────────────────────────────────

def _get_or_create_store_page(seller):
    """Return this seller's StorePage, creating it if it doesn't exist yet.

    This prevents fallback to another seller's page (M2 isolation).
    """
    store_page, created = StorePage.objects.get_or_create(
        slug=seller.slug,
        defaults={
            "title": seller.name,
            "description": seller.bio or "",
            "is_published": False,
            "seller": seller,
        },
    )
    if store_page.seller_id is None:
        # Backfill rows created before this FK was set at creation time.
        store_page.seller = seller
        store_page.save(update_fields=["seller"])
    return store_page


@seller_required
def store(request):
    seller = request.seller
    store_page = _get_or_create_store_page(seller)

    if request.method == "POST":
        form = StorePageForm(request.POST, request.FILES, instance=store_page)
        theme_form = ThemeForm(request.POST, request.FILES)
        if form.is_valid() and theme_form.is_valid():
            store_page = form.save(commit=False)
            banner = theme_form.cleaned_data.get("banner")
            if banner:
                store_page.banner = banner
            store_page.theme = {
                "primary_color": theme_form.cleaned_data.get("primary_color") or "#4f46e5",
                "background_color": theme_form.cleaned_data.get("background_color") or "#f9fafb",
                "layout": theme_form.cleaned_data.get("layout") or "default",
                "button_style": theme_form.cleaned_data.get("button_style") or "rounded",
                "instagram": theme_form.cleaned_data.get("instagram") or "",
                "tiktok": theme_form.cleaned_data.get("tiktok") or "",
                "youtube": theme_form.cleaned_data.get("youtube") or "",
                "twitter": theme_form.cleaned_data.get("twitter") or "",
                "website": theme_form.cleaned_data.get("website") or "",
            }
            store_page.save()
            messages.success(request, "Store settings saved successfully.")
            return redirect("seller:store")
    else:
        form = StorePageForm(instance=store_page)
        theme_form = ThemeForm(initial=store_page.theme)

    blocks = store_page.blocks.select_related("product").order_by("position", "pk")
    already_blocked_pks = store_page.blocks.values_list("product_id", flat=True)
    available_products = _seller_products(seller).exclude(pk__in=already_blocked_pks).order_by("name")

    return render(request, "seller/store.html", {
        "seller": seller,
        "store_page": store_page,
        "form": form,
        "theme_form": theme_form,
        "blocks": blocks,
        "available_products": available_products,
    })


@seller_required
@require_POST
def store_publish_toggle(request):
    """Toggle store published / draft status."""
    seller = request.seller
    store_page = _get_or_create_store_page(seller)
    store_page.is_published = not store_page.is_published
    store_page.save(update_fields=["is_published", "updated_at"])
    if store_page.is_published:
        messages.success(request, "Store is now Live — visitors can see it.")
    else:
        messages.success(request, "Store is now Draft — hidden from public.")
    return redirect("seller:store")


@seller_required
@require_POST
def block_add(request):
    """Add a product block to the store page."""
    seller = request.seller
    store_page = _get_or_create_store_page(seller)
    product_pk = request.POST.get("product_pk")
    if product_pk:
        product = get_object_or_404(_seller_products(seller), pk=product_pk)
        position = (store_page.blocks.aggregate(m=Count("pk"))["m"] or 0) + 1
        _, created = Block.objects.get_or_create(
            store_page=store_page, product=product,
            defaults={"type": Block.Type.PRODUCT, "position": position},
        )
        if created:
            messages.success(request, f"'{product.name}' added to your store.")
        else:
            messages.info(request, f"'{product.name}' is already in your store.")
    else:
        messages.error(request, "Please select a product to add.")
    return redirect("seller:store")


@seller_required
@require_POST
def block_remove(request, block_pk):
    """Remove a block from the store page."""
    seller = request.seller
    store_page = _get_or_create_store_page(seller)
    block = get_object_or_404(Block, pk=block_pk, store_page=store_page)
    name = block.product.name if block.product else "Block"
    block.delete()
    messages.success(request, f"'{name}' removed from your store.")
    return redirect("seller:store")


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "fetch"


@seller_required
@require_POST
def block_toggle_visibility(request, block_pk):
    """Toggle a block's visibility on the store page."""
    seller = request.seller
    store_page = _get_or_create_store_page(seller)
    block = get_object_or_404(Block, pk=block_pk, store_page=store_page)
    block.is_visible = not block.is_visible
    block.save(update_fields=["is_visible", "updated_at"])
    if _is_ajax(request):
        return JsonResponse({"is_visible": block.is_visible})
    messages.success(request, f"Block is now {'visible' if block.is_visible else 'hidden'}.")
    return redirect("seller:store")


@seller_required
@require_POST
def block_reorder(request):
    """Persist a new block order. Body: order=<pk>,<pk>,… (all of the store's blocks)."""
    seller = request.seller
    store_page = _get_or_create_store_page(seller)
    raw = request.POST.get("order", "")
    try:
        ids = [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        return JsonResponse({"error": "bad order"}, status=400)

    owned = set(store_page.blocks.values_list("pk", flat=True))
    if set(ids) != owned:
        return JsonResponse({"error": "order must list every block exactly once"}, status=400)

    for position, pk in enumerate(ids, start=1):
        Block.objects.filter(pk=pk, store_page=store_page).update(position=position)

    if _is_ajax(request):
        return JsonResponse({"ok": True})
    messages.success(request, "Block order updated.")
    return redirect("seller:store")


# ── Vouchers (coupons) ────────────────────────────────────────────────────────

@seller_required
def vouchers(request):
    seller = request.seller
    coupon_list = Coupon.objects.filter(seller=seller).order_by("-created_at")
    return render(request, "seller/vouchers.html", {
        "seller": seller,
        "coupons": coupon_list,
    })


@seller_required
def voucher_create(request):
    seller = request.seller
    if request.method == "POST":
        form = CouponForm(request.POST)
        if form.is_valid():
            coupon = form.save(commit=False)
            coupon.seller = seller
            coupon.code = coupon.code.upper()
            coupon.save()
            form.save_m2m()
            messages.success(request, f"Voucher {coupon.code} created.")
            return redirect("seller:vouchers")
    else:
        form = CouponForm()
    return render(request, "seller/voucher_form.html", {
        "seller": seller,
        "form": form,
        "title": "New Voucher",
        "submit_label": "Create Voucher",
    })


@seller_required
def voucher_edit(request, pk):
    seller = request.seller
    coupon = get_object_or_404(Coupon, pk=pk, seller=seller)
    if request.method == "POST":
        form = CouponForm(request.POST, instance=coupon)
        if form.is_valid():
            c = form.save(commit=False)
            c.code = c.code.upper()
            c.save()
            form.save_m2m()
            messages.success(request, "Voucher updated.")
            return redirect("seller:vouchers")
    else:
        form = CouponForm(instance=coupon)
    return render(request, "seller/voucher_form.html", {
        "seller": seller,
        "form": form,
        "coupon": coupon,
        "title": f"Edit — {coupon.code}",
        "submit_label": "Save Voucher",
    })


@seller_required
def voucher_toggle(request, pk):
    """Toggle coupon active/inactive."""
    seller = request.seller
    coupon = get_object_or_404(Coupon, pk=pk, seller=seller)
    if request.method == "POST":
        coupon.is_active = not coupon.is_active
        coupon.save(update_fields=["is_active", "updated_at"])
    return redirect("seller:vouchers")


# ── Broadcast ─────────────────────────────────────────────────────────────────

@seller_required
def broadcast(request):
    seller = request.seller
    if request.method == "POST":
        form = BroadcastForm(request.POST)
        if form.is_valid():
            segment = form.cleaned_data["segment"]
            message_tpl = form.cleaned_data["message"]
            product = form.cleaned_data.get("product")

            customers = _get_segment_customers(seller, segment, product)
            queued = 0
            for customer in customers:
                wa = customer.wa_number or customer.user.email
                msg = message_tpl.replace("{name}", customer.user.email.split("@")[0])
                deliver_whatsapp.delay(wa, msg)
                queued += 1

            messages.success(request, f"Broadcast queued for {queued} customer(s).")
            return redirect("seller:broadcast")
    else:
        form = BroadcastForm()

    return render(request, "seller/broadcast.html", {
        "seller": seller,
        "form": form,
    })


def _get_segment_customers(seller, segment, product=None):
    qs = Customer.objects.select_related("user")
    if segment == "active_sub":
        plans = _seller_products(seller).values_list("plans", flat=True)
        qs = qs.filter(
            subscriptions__plan__in=plans,
            subscriptions__status=Subscription.Status.ACTIVE,
        ).distinct()
    elif segment == "no_sub":
        plans = _seller_products(seller).values_list("plans", flat=True)
        qs = qs.exclude(
            subscriptions__plan__in=plans,
            subscriptions__status=Subscription.Status.ACTIVE,
        ).distinct()
    if product:
        qs = qs.filter(orders__plan__product=product, orders__status=Order.Status.PAID).distinct()
    return qs


# ── Analytics ────────────────────────────────────────────────────────────────

@seller_required
def analytics(request):
    from apps.storefront.models import PageEvent
    seller = request.seller
    products = _seller_products(seller)

    days = int(request.GET.get("days", 30))
    days = max(7, min(days, 90))
    since = timezone.now() - timezone.timedelta(days=days)

    funnel_qs = PageEvent.objects.filter(created_at__gte=since)
    product_pks = list(products.values_list("pk", flat=True))

    page_views = funnel_qs.filter(event="page_view").count()
    product_views = funnel_qs.filter(event="product_view", product_id__in=product_pks).count()
    checkout_starts = funnel_qs.filter(event="checkout_start", product_id__in=product_pks).count()
    orders_paid = funnel_qs.filter(event="order_paid", product_id__in=product_pks).count()

    from django.db.models.functions import TruncDate
    daily_paid = (
        funnel_qs.filter(event="order_paid", product_id__in=product_pks)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(cnt=Count("pk"))
        .order_by("day")
    )
    daily_map = {row["day"]: row["cnt"] for row in daily_paid}
    chart_days = []
    today = timezone.now().date()
    for i in range(min(days, 30) - 1, -1, -1):
        d = today - timezone.timedelta(days=i)
        chart_days.append({"date": d, "label": d.strftime("%d/%m"), "cnt": daily_map.get(d, 0)})
    chart_max = max((d["cnt"] for d in chart_days), default=1) or 1

    top_products = (
        funnel_qs.filter(event="order_paid", product_id__in=product_pks)
        .values("product__name")
        .annotate(cnt=Count("pk"))
        .order_by("-cnt")[:10]
    )

    return render(request, "seller/analytics.html", {
        "seller": seller,
        "days": days,
        "page_views": page_views,
        "product_views": product_views,
        "checkout_starts": checkout_starts,
        "orders_paid": orders_paid,
        "chart_days": chart_days,
        "chart_max": chart_max,
        "top_products": top_products,
    })


# ── Settings ──────────────────────────────────────────────────────────────────

@seller_required
def settings(request):
    seller = request.seller
    if request.method == "POST":
        form = SellerProfileForm(request.POST, request.FILES, instance=seller)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("seller:settings")
    else:
        form = SellerProfileForm(instance=seller)
    return render(request, "seller/settings.html", {
        "seller": seller,
        "form": form,
    })


# ── Apply (seller application) ────────────────────────────────────────────────

def apply(request):
    """Logged-in, email-verified users apply to become a seller — approved instantly
    (no manual review step, see docs/feedback — is_approved stays available for
    later moderation/suspension, it's just no longer part of the application path).
    """
    if not request.user.is_authenticated:
        return redirect("/accounts/login/?next=/seller/apply/")

    try:
        seller = request.user.seller_profile
        if not seller.is_approved:
            # Only reachable for accounts suspended after the fact (moderation) —
            # instant approval means nothing is created in a not-approved state anymore.
            return render(request, "seller/apply.html", {"suspended": True})
        if not seller.onboarding_completed:
            return redirect("seller:onboarding")
        return redirect("seller:home")
    except SellerProfile.DoesNotExist:
        pass

    from allauth.account.models import EmailAddress
    email_verified = EmailAddress.objects.filter(user=request.user, verified=True).exists()

    if request.method == "POST":
        if not email_verified:
            messages.error(request, "Please verify your email before applying as a seller.")
            return redirect("account_email")
        name = request.POST.get("store_name", "").strip()
        slug_candidate = slugify(name)
        if not name:
            messages.error(request, "Store name is required.")
        elif SellerProfile.objects.filter(slug=slug_candidate).exists():
            messages.error(request, "That store name is already taken.")
        else:
            SellerProfile.objects.create(
                user=request.user,
                name=name,
                slug=slug_candidate,
                is_approved=True,
                onboarding_completed=False,
            )
            messages.success(request, "You're in! Let's set up your store.")
            return redirect("seller:onboarding")

    return render(request, "seller/apply.html", {"suspended": False, "email_verified": email_verified})


# ── Onboarding (mandatory first-time store setup wizard) ─────────────────────

def onboarding(request):
    """Mandatory 3-step wizard a new seller must finish before reaching the regular
    dashboard (see docs/feedback — deliberately not skippable, unlike a typical
    dismissible-nudge onboarding flow).

    Steps: identity (store name/avatar/bio) -> product (one sellable plan) ->
    publish (go live). seller.onboarding_step tracks resume position; seller_required
    (apps/seller/decorators.py) redirects here for any seller who hasn't finished.
    """
    if not request.user.is_authenticated:
        return redirect("/accounts/login/?next=/seller/onboarding/")

    try:
        seller = request.user.seller_profile
    except SellerProfile.DoesNotExist:
        return redirect("seller:apply")

    if not seller.is_approved:
        return redirect("seller:apply")

    if seller.onboarding_completed:
        return redirect("seller:home")

    store_page = _get_or_create_store_page(seller)
    step = seller.onboarding_step

    if step == SellerProfile.OnboardingStep.IDENTITY:
        if request.method == "POST":
            form = StorePageForm(request.POST, request.FILES, instance=store_page)
            if form.is_valid():
                form.save()
                seller.onboarding_step = SellerProfile.OnboardingStep.PRODUCT
                seller.save(update_fields=["onboarding_step", "updated_at"])
                return redirect("seller:onboarding")
        else:
            form = StorePageForm(instance=store_page)
        return render(request, "seller/onboarding.html", {
            "seller": seller, "step": step, "form": form, "store_page": store_page,
        })

    if step == SellerProfile.OnboardingStep.PRODUCT:
        if request.method == "POST":
            form = OnboardingProductForm(request.POST)
            if form.is_valid():
                product = Product.objects.create(
                    seller=seller if not seller.user.is_superuser else None,
                    name=form.cleaned_data["product_name"],
                    type=Product.Type.FREE if form.cleaned_data["price"] == 0 else Product.Type.ONE_TIME,
                    visibility=Product.Visibility.PUBLIC,
                )
                plan = Plan.objects.create(
                    seller=product.seller,
                    product=product,
                    name="Standard",
                    price=form.cleaned_data["price"],
                )
                position = (store_page.blocks.aggregate(m=Count("pk"))["m"] or 0) + 1
                Block.objects.create(store_page=store_page, product=product, type=Block.Type.PRODUCT, position=position)
                seller.onboarding_step = SellerProfile.OnboardingStep.PUBLISH
                seller.save(update_fields=["onboarding_step", "updated_at"])
                return redirect("seller:onboarding")
        else:
            form = OnboardingProductForm()
        return render(request, "seller/onboarding.html", {
            "seller": seller, "step": step, "form": form, "store_page": store_page,
        })

    # step == PUBLISH
    if request.method == "POST":
        store_page.is_published = True
        store_page.save(update_fields=["is_published", "updated_at"])
        seller.onboarding_completed = True
        seller.save(update_fields=["onboarding_completed", "updated_at"])
        messages.success(request, "Your store is live!")
        return redirect("seller:home")

    product = _seller_products(seller).prefetch_related("plans").first()
    return render(request, "seller/onboarding.html", {
        "seller": seller, "step": step, "store_page": store_page, "product": product,
    })


# ── Earnings & Payouts ────────────────────────────────────────────────────────

@seller_required
def earnings(request):
    seller = request.seller
    all_earnings = SellerEarning.objects.filter(seller=seller).select_related("order__plan__product")
    total_gross = all_earnings.filter(status=SellerEarning.Status.PENDING).aggregate(s=Sum("gross"))["s"] or 0
    total_net = all_earnings.filter(status=SellerEarning.Status.PENDING).aggregate(s=Sum("net"))["s"] or 0
    total_commission = all_earnings.filter(status=SellerEarning.Status.PENDING).aggregate(s=Sum("commission"))["s"] or 0
    paid_out = all_earnings.filter(status=SellerEarning.Status.PAID_OUT).aggregate(s=Sum("net"))["s"] or 0
    recent_payouts = SellerPayout.objects.filter(seller=seller).order_by("-created_at")[:10]
    payout_form = PayoutRequestForm(initial={"amount": total_net})
    return render(request, "seller/earnings.html", {
        "seller": seller,
        "earnings": all_earnings[:50],
        "total_gross": total_gross,
        "total_net": total_net,
        "total_commission": total_commission,
        "paid_out": paid_out,
        "recent_payouts": recent_payouts,
        "payout_form": payout_form,
    })


@seller_required
@require_POST
def payout_request(request):
    seller = request.seller
    if not seller.payout_bank_name or not seller.payout_account_number:
        messages.error(request, "Please add your bank account details in Settings before requesting a payout.")
        return redirect("seller:settings")

    form = PayoutRequestForm(request.POST)
    if form.is_valid():
        amount = form.cleaned_data["amount"]
        available = SellerEarning.objects.filter(
            seller=seller, status=SellerEarning.Status.PENDING
        ).aggregate(s=Sum("net"))["s"] or 0

        if amount > available:
            messages.error(request, f"Requested amount exceeds available balance (Rp{available:,}).")
        else:
            SellerPayout.objects.create(
                seller=seller,
                amount=amount,
                bank_name=seller.payout_bank_name,
                account_number=seller.payout_account_number,
                account_name=seller.payout_account_name,
            )
            messages.success(request, f"Payout request for Rp{amount:,} submitted. Processing in 1–3 business days.")
    else:
        messages.error(request, "Invalid amount.")
    return redirect("seller:earnings")


# ── Affiliates ────────────────────────────────────────────────────────────────

@seller_required
def affiliates(request):
    seller = request.seller
    links = AffiliateLink.objects.filter(seller=seller).select_related("product").annotate(
        commission_total=Sum("commissions__amount"),
        commission_count=Count("commissions"),
    ).order_by("-created_at")

    form = AffiliateLinkForm(seller)
    if request.method == "POST":
        form = AffiliateLinkForm(seller, request.POST)
        if form.is_valid():
            link = form.save(commit=False)
            link.seller = seller
            link.code = link.code.upper()
            link.save()
            messages.success(request, f"Affiliate link /{link.code} created.")
            return redirect("seller:affiliates")

    return render(request, "seller/affiliates.html", {
        "seller": seller,
        "links": links,
        "form": form,
    })


@seller_required
@require_POST
def affiliate_toggle(request, link_pk):
    seller = request.seller
    link = get_object_or_404(AffiliateLink, pk=link_pk, seller=seller)
    link.is_active = not link.is_active
    link.save(update_fields=["is_active", "updated_at"])
    status = "activated" if link.is_active else "deactivated"
    messages.success(request, f"Affiliate link {link.code} {status}.")
    return redirect("seller:affiliates")


# ── Subscriptions ─────────────────────────────────────────────────────────────

_SENSITIVE_PAYLOAD_KEYS = {
    "download_url", "access_url", "password", "api_key",
    "key", "token", "secret", "license_key",
}

_FIELD_LABELS = {
    "download_url": "Download URL",
    "access_url": "Access URL",
    "username": "Username",
    "password": "Password",
    "api_key": "API Key",
    "key": "Key",
    "token": "Token",
    "secret": "Secret",
    "license_key": "License Key",
    "license_id": "License ID",
    "product_name": "Course",
    "product_id": "Course ID",
}


def _build_grant_data(grants_qs):
    """Return list of dicts with classified payload fields for template rendering."""
    import json as _json
    from apps.provisioning.crypto import decrypt as _decrypt

    result = []
    for g in grants_qs:
        visible = []
        secrets = []

        for k, v in g.payload.items():
            label = _FIELD_LABELS.get(k, k.replace("_", " ").title())
            if k in _SENSITIVE_PAYLOAD_KEYS:
                secrets.append((label, str(v)))
            else:
                visible.append((label, str(v)))

        try:
            plain = _decrypt(g.secret.ciphertext)
            for k, v in _json.loads(plain).items():
                label = _FIELD_LABELS.get(k, k.replace("_", " ").title())
                existing_labels = {s[0] for s in secrets}
                if label not in existing_labels:
                    secrets.append((label, str(v)))
        except Exception:
            pass

        result.append({
            "grant": g,
            "visible": visible,
            "secrets": secrets,
            "instructions": g.deliverable.instructions or "",
            "has_data": bool(visible or secrets),
        })
    return result


def _seller_subscriptions(seller):
    products = _seller_products(seller)
    return Subscription.objects.filter(plan__product__in=products).select_related(
        "customer__user", "plan__product"
    )


@seller_required
def subscriptions(request):
    seller = request.seller
    status_filter = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()

    qs = _seller_subscriptions(seller).order_by("-created_at")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if search:
        qs = qs.filter(
            Q(customer__user__email__icontains=search) |
            Q(plan__name__icontains=search) |
            Q(plan__product__name__icontains=search)
        )

    all_subs = _seller_subscriptions(seller)
    stats = {
        "active": all_subs.filter(status=Subscription.Status.ACTIVE).count(),
        "grace": all_subs.filter(status=Subscription.Status.GRACE).count(),
        "suspended": all_subs.filter(status=Subscription.Status.SUSPENDED).count(),
        "cancelled": all_subs.filter(status=Subscription.Status.CANCELLED).count(),
    }

    return render(request, "seller/subscriptions.html", {
        "seller": seller,
        "subscriptions": qs[:200],
        "status_filter": status_filter,
        "search": search,
        "stats": stats,
        "status_choices": Subscription.Status.choices,
        "now": timezone.now(),
    })


@seller_required
@require_POST
def subscription_cancel(request, sub_pk):
    seller = request.seller
    sub = get_object_or_404(
        Subscription, pk=sub_pk, plan__product__in=_seller_products(seller)
    )
    if sub.status in (Subscription.Status.ACTIVE, Subscription.Status.GRACE):
        sub.status = Subscription.Status.CANCELLED
        sub.auto_renew = False
        sub.save(update_fields=["status", "auto_renew", "updated_at"])
        messages.success(request, f"Subscription #{sub.pk} ({sub.customer.user.email}) has been cancelled.")
    else:
        messages.warning(request, "Subscription is already cancelled or suspended.")
    next_url = request.POST.get("next", "")
    if next_url == "detail":
        return redirect("seller:subscription_detail", pk=sub_pk)
    return redirect("seller:subscriptions")


@seller_required
def subscription_detail(request, pk):
    seller = request.seller
    sub = get_object_or_404(
        Subscription.objects.select_related("customer__user", "plan__product"),
        pk=pk,
        plan__product__in=_seller_products(seller),
    )

    related_orders = list(
        sub.orders.select_related("customer__user", "plan__product", "coupon")
        .order_by("created_at")
    )

    total_revenue = sum(o.amount for o in related_orders if o.status == Order.Status.PAID)
    now = timezone.now()
    diff = sub.current_period_end - now
    days_remaining = diff.days
    is_expired = sub.current_period_end < now

    grant_data = _build_grant_data(sub.grants.select_related("deliverable").order_by("created_at"))

    return render(request, "seller/subscription_detail.html", {
        "seller": seller,
        "sub": sub,
        "related_orders": related_orders,
        "total_revenue": total_revenue,
        "days_remaining": days_remaining,
        "days_overdue": abs(days_remaining),
        "is_expired": is_expired,
        "now": now,
        "grant_data": grant_data,
    })


@seller_required
@require_POST
def subscription_toggle_suspend(request, sub_pk):
    seller = request.seller
    sub = get_object_or_404(
        Subscription, pk=sub_pk, plan__product__in=_seller_products(seller)
    )
    if sub.status == Subscription.Status.SUSPENDED:
        sub.status = Subscription.Status.ACTIVE
        sub.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Subscription #{sub.pk} reactivated.")
    elif sub.status in (Subscription.Status.ACTIVE, Subscription.Status.GRACE):
        sub.status = Subscription.Status.SUSPENDED
        sub.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Subscription #{sub.pk} suspended.")
    else:
        messages.warning(request, "Cannot change status of a cancelled subscription.")
    return redirect("seller:subscription_detail", pk=sub_pk)


@seller_required
@require_POST
def subscription_toggle_renew(request, sub_pk):
    seller = request.seller
    sub = get_object_or_404(
        Subscription, pk=sub_pk, plan__product__in=_seller_products(seller)
    )
    sub.auto_renew = not sub.auto_renew
    sub.save(update_fields=["auto_renew", "updated_at"])
    label = "enabled" if sub.auto_renew else "disabled"
    messages.success(request, f"Auto-renew {label} for subscription #{sub.pk}.")
    return redirect("seller:subscription_detail", pk=sub_pk)
