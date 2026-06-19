"""Seller Dashboard views — Lynk.id-style creator interface at /seller/."""
import json
import logging

from django.contrib import messages
from django.db.models import Count, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Customer, SellerProfile
from apps.billing.models import Coupon, Order, Subscription
from apps.catalog.models import Plan, Product
from apps.notifications.whatsapp import send_whatsapp as send_wa
from apps.provisioning.models import Deliverable
from apps.storefront.models import Block, StorePage

from .decorators import seller_required
from .forms import (
    BlockOrderForm,
    BroadcastForm,
    CouponForm,
    DeliverableForm,
    PlanForm,
    ProductForm,
    SellerProfileForm,
    StorePageForm,
)

logger = logging.getLogger(__name__)


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

    return render(request, "seller/home.html", {
        "seller": seller,
        "revenue": revenue,
        "orders_count": orders_count,
        "active_subs": active_subs,
        "pending_orders": pending_orders,
        "recent_orders": recent_orders,
        "products_count": products_count,
    })


# ── Products ──────────────────────────────────────────────────────────────────

@seller_required
def products(request):
    seller = request.seller
    product_list = _seller_products(seller).prefetch_related("plans").order_by("name")
    return render(request, "seller/products.html", {
        "seller": seller,
        "products": product_list,
    })


@seller_required
def product_create(request):
    seller = request.seller
    if request.method == "POST":
        form = ProductForm(request.POST)
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
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, "Product updated.")
            return redirect("seller:product_edit", pk=product.pk)
    else:
        form = ProductForm(instance=product)

    plans = product.plans.all()
    deliverables = Deliverable.objects.filter(plan__product=product).select_related("plan")
    return render(request, "seller/product_form.html", {
        "seller": seller,
        "form": form,
        "product": product,
        "plans": plans,
        "deliverables": deliverables,
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
    return render(request, "seller/plan_form.html", {
        "seller": seller,
        "product": product,
        "plan": plan,
        "form": form,
        "deliverable_form": deliverable_form,
        "title": f"Edit Plan — {plan.name}",
        "submit_label": "Save Plan",
    })


# ── Orders ────────────────────────────────────────────────────────────────────

@seller_required
def orders(request):
    seller = request.seller
    status_filter = request.GET.get("status", "")
    qs = _seller_orders(seller).order_by("-created_at")
    if status_filter:
        qs = qs.filter(status=status_filter)
    return render(request, "seller/orders.html", {
        "seller": seller,
        "orders": qs[:100],
        "status_filter": status_filter,
        "status_choices": Order.Status.choices,
    })


# ── Store (StorePage editor) ──────────────────────────────────────────────────

@seller_required
def store(request):
    seller = request.seller
    store_page = StorePage.objects.filter(slug=seller.slug).first()
    if store_page is None:
        store_page = StorePage.objects.first()

    if request.method == "POST":
        form = StorePageForm(request.POST, instance=store_page)
        if form.is_valid():
            form.save()
            messages.success(request, "Store page updated.")
            return redirect("seller:store")
    else:
        form = StorePageForm(instance=store_page)

    blocks = store_page.blocks.select_related("product").order_by("position") if store_page else []
    seller_products = _seller_products(seller).filter(visibility=Product.Visibility.PUBLIC)

    return render(request, "seller/store.html", {
        "seller": seller,
        "store_page": store_page,
        "form": form,
        "blocks": blocks,
        "available_products": seller_products,
    })


@seller_required
def block_add(request):
    """HTMX: add a product block to the store page."""
    seller = request.seller
    if request.method != "POST":
        raise Http404
    store_page = StorePage.objects.filter(slug=seller.slug).first() or StorePage.objects.first()
    product_pk = request.POST.get("product_pk")
    if product_pk:
        product = get_object_or_404(_seller_products(seller), pk=product_pk)
        position = (store_page.blocks.aggregate(m=Count("pk"))["m"] or 0) + 1
        Block.objects.get_or_create(
            store_page=store_page, product=product,
            defaults={"type": Block.Type.PRODUCT, "position": position},
        )
    return redirect("seller:store")


@seller_required
def block_remove(request, block_pk):
    """Remove a block from the store page."""
    seller = request.seller
    store_page = StorePage.objects.filter(slug=seller.slug).first() or StorePage.objects.first()
    block = get_object_or_404(Block, pk=block_pk, store_page=store_page)
    if request.method == "POST":
        block.delete()
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
            sent = 0
            for customer in customers:
                wa = customer.wa_number or customer.user.email
                msg = message_tpl.replace("{name}", customer.user.email.split("@")[0])
                try:
                    send_wa(wa, msg)
                    sent += 1
                except Exception:
                    logger.warning("Broadcast WA failed for %s", customer.user.email)

            messages.success(request, f"Broadcast sent to {sent} customer(s).")
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


# ── Settings ──────────────────────────────────────────────────────────────────

@seller_required
def settings(request):
    seller = request.seller
    if request.method == "POST":
        form = SellerProfileForm(request.POST, instance=seller)
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
    """Non-authenticated users / customers apply to become a seller."""
    from django.contrib.auth.decorators import login_required
    if not request.user.is_authenticated:
        return redirect("/accounts/login/?next=/seller/apply/")

    try:
        seller = request.user.seller_profile
        if seller.is_approved:
            return redirect("seller:home")
        # Already applied — show pending message
        return render(request, "seller/apply.html", {"pending": True})
    except SellerProfile.DoesNotExist:
        pass

    if request.method == "POST":
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
                is_approved=False,
            )
            messages.success(request, "Application submitted! You'll be notified when approved.")
            return redirect("seller:apply")

    return render(request, "seller/apply.html", {"pending": False})
