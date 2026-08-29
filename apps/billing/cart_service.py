"""Shopping cart service — add/remove lines, pricing, and multi-item checkout.

v1 scope (docs/feedback section H): a cart can hold plans from different sellers.
Sumopod is configured once for the whole platform (no per-seller merchant credentials),
so a multi-seller cart still checks out with a single combined invoice when the
wallet balance falls short — each Order still gets its own seller-earning record,
same as single-item checkout. PWYW plans and plans whose product has required
intake questions are not addable to cart; those still use the direct single-plan
checkout page.
"""
import logging

from django.db import IntegrityError, transaction

from apps.billing.models import Cart, CartCheckout, CartItem, Coupon, Order
from apps.catalog.models import Plan
from apps.core.events import emit
from apps.wallet.exceptions import InsufficientBalance
from apps.wallet.models import LedgerEntry
from apps.wallet.services import debit

logger = logging.getLogger(__name__)

SESSION_CART_ID_KEY = "cart_id"


class CartError(Exception):
    """Base class for cart validation errors shown to the buyer."""


class PlanNotCartableError(CartError):
    """Plan is PWYW or its product has required custom questions."""


class EmptyCartError(CartError):
    """checkout_cart() called with no items."""


class CartPaymentMethodRequiredError(CartError):
    """A TopUp is needed to cover the shortfall but no payment_method was given."""


# ── Cart resolution (session for guests, customer once logged in) ──────────────

def get_or_create_cart(request):
    """Return the active Cart for this request, merging a guest session cart
    into the customer's cart the first time an authenticated request arrives.
    """
    if request.user.is_authenticated:
        from apps.storefront.views import _get_or_create_customer
        customer, _ = _get_or_create_customer(request.user)

        cart, _ = Cart.objects.get_or_create(customer=customer)

        session_cart_id = request.session.get(SESSION_CART_ID_KEY)
        if session_cart_id and session_cart_id != cart.pk:
            _merge_cart(source_id=session_cart_id, target=cart)
            del request.session[SESSION_CART_ID_KEY]

        return cart

    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    cart_id = request.session.get(SESSION_CART_ID_KEY)
    if cart_id:
        cart = Cart.objects.filter(pk=cart_id, customer__isnull=True).first()
        if cart:
            return cart

    cart = Cart.objects.create(session_key=session_key)
    request.session[SESSION_CART_ID_KEY] = cart.pk
    return cart


def _merge_cart(*, source_id, target: Cart) -> None:
    """Move any lines from a guest session cart into the now-authenticated
    customer's cart, skipping plans already present, then delete the empty cart.
    """
    try:
        source = Cart.objects.get(pk=source_id, customer__isnull=True)
    except Cart.DoesNotExist:
        return
    existing_plan_ids = set(target.items.values_list("plan_id", flat=True))
    for item in source.items.all():
        if item.plan_id not in existing_plan_ids:
            item.pk = None
            item.cart = target
            item.save()
    source.delete()


# ── Add / remove / update lines ─────────────────────────────────────────────────

def add_to_cart(cart: Cart, plan: Plan, *, duration_multiplier: int = 1, coupon_code: str = "") -> CartItem:
    if plan.pwyw:
        raise PlanNotCartableError("This plan requires entering your own price — use the checkout page directly.")
    if plan.product.questions.exists():
        raise PlanNotCartableError("This product needs extra details at checkout — use the checkout page directly.")

    try:
        with transaction.atomic():
            item, created = CartItem.objects.get_or_create(
                cart=cart, plan=plan,
                defaults={"duration_multiplier": max(1, duration_multiplier), "coupon_code": coupon_code.strip().upper()},
            )
    except IntegrityError:
        item = CartItem.objects.get(cart=cart, plan=plan)
        created = False
    if not created:
        item.duration_multiplier = max(1, duration_multiplier)
        item.coupon_code = coupon_code.strip().upper()
        item.save(update_fields=["duration_multiplier", "coupon_code", "updated_at"])
    return item


def remove_from_cart(cart: Cart, item_pk: int) -> None:
    CartItem.objects.filter(cart=cart, pk=item_pk).delete()


def update_cart_item(cart: Cart, item_pk: int, *, duration_multiplier: int) -> None:
    CartItem.objects.filter(cart=cart, pk=item_pk).update(duration_multiplier=max(1, duration_multiplier))


# ── Pricing ──────────────────────────────────────────────────────────────────────

def compute_cart_line(item: CartItem):
    """Return (effective_price, discount, coupon_obj, base_price) for one line —
    mirrors apps.billing.checkout.checkout()'s duration + coupon math.
    """
    plan = item.plan
    dm = max(1, item.duration_multiplier) if plan.interval != Plan.Interval.NONE else 1
    base_price = plan.price
    if dm > 1:
        subtotal = base_price * dm
        disc_pct = int(plan.duration_discounts.get(str(dm), 0))
        base_price = subtotal - (subtotal * disc_pct // 100)

    coupon_obj = None
    discount = 0
    if item.coupon_code:
        try:
            coupon_obj = Coupon.objects.get(code=item.coupon_code)
            valid, _reason = coupon_obj.is_valid_for(plan)
            if valid:
                discount = coupon_obj.compute_discount(base_price)
            else:
                coupon_obj = None
        except Coupon.DoesNotExist:
            pass

    effective_price = max(0, base_price - discount)
    return effective_price, discount, coupon_obj, base_price


def cart_total(cart: Cart) -> int:
    return sum(compute_cart_line(item)[0] for item in cart.items.select_related("plan").all())


# ── Checkout ─────────────────────────────────────────────────────────────────────

def _increment_coupon_usage(coupon: Coupon) -> None:
    from django.db.models import F, Q
    updated = Coupon.objects.filter(
        Q(usage_limit=0) | Q(used_count__lt=F("usage_limit")), pk=coupon.pk,
    ).update(used_count=F("used_count") + 1)
    if not updated and coupon.usage_limit > 0:
        logger.warning("Cart checkout: coupon %s hit its usage limit mid-checkout", coupon.code)


def checkout_cart(customer, cart: Cart, *, callback_url: str = "", return_url: str,
                   payment_method: str | None = None, gateway_client=None,
                   payment_proof=None, selected_item_ids=None):
    """Check out the cart. Returns (cart_checkout, grants, payment_url) —
    payment_url is None when fully paid from wallet balance (cart_checkout.status is
    already COMPLETED in that case); grants is [] when a TopUp is needed (orders stay
    PENDING, cart_checkout stays PENDING, until the webhook completes them).

    selected_item_ids: if given, only those CartItems are checked out and removed;
    the rest stay in the cart. None means "every line".

    A CartCheckout row is always created (even when paid immediately from wallet
    balance) so there's one canonical receipt page for both paths.
    """
    from apps.billing.checkout import _assign_invoice_number, _create_subscription, _provision_order, _record_seller_earning

    items = list(cart.items.select_related("plan__product").all())
    if selected_item_ids is not None:
        wanted = {int(i) for i in selected_item_ids}
        items = [i for i in items if i.pk in wanted]
    if not items:
        raise EmptyCartError("Your cart is empty.")

    checked_out_ids = [i.pk for i in items]
    lines = [(item, *compute_cart_line(item)) for item in items]
    total = sum(price for _item, price, _discount, _coupon, _base in lines)

    # ── Static QRIS — one seller, buyer pays the seller's static QR directly ──
    if payment_method == Order.PaymentChannel.QRIS_STATIC:
        seller_ids = {item.plan.product.seller_id for item, *_ in lines}
        seller = items[0].plan.product.seller
        if len(seller_ids) != 1 or seller is None or not seller.qris_ready:
            raise CartError("Static QRIS is only available when every item is from one seller who accepts it.")
        with transaction.atomic():
            cart_checkout = CartCheckout.objects.create(customer=customer, status=CartCheckout.Status.PENDING)
            for i, (item, price, discount, coupon_obj, _base) in enumerate(lines):
                Order.objects.create(
                    customer=customer,
                    plan=item.plan,
                    amount=price,
                    discount=discount,
                    coupon=coupon_obj if discount > 0 else None,
                    status=Order.Status.PENDING,
                    payment_channel=Order.PaymentChannel.QRIS_STATIC,
                    payment_proof=payment_proof if i == 0 else None,
                    duration_multiplier=item.duration_multiplier,
                    cart_checkout=cart_checkout,
                    idempotency_key=f"cart:{cart.pk}:item:{item.pk}",
                )
            cart.items.filter(pk__in=checked_out_ids).delete()
        emit("order.awaiting_confirmation", customer_id=customer.pk,
             order_id=cart_checkout.orders.first().pk, plan_name="cart checkout")
        return cart_checkout, [], None

    wallet = customer.wallet
    wallet.refresh_from_db()

    if wallet.balance >= total:
        cart_checkout = CartCheckout.objects.create(customer=customer, status=CartCheckout.Status.COMPLETED)
        grants_all = []
        with transaction.atomic():
            for item, price, discount, coupon_obj, _base in lines:
                order = Order.objects.create(
                    customer=customer,
                    plan=item.plan,
                    amount=price,
                    discount=discount,
                    coupon=coupon_obj if discount > 0 else None,
                    status=Order.Status.PENDING,
                    duration_multiplier=item.duration_multiplier,
                    cart_checkout=cart_checkout,
                    idempotency_key=f"cart:{cart.pk}:item:{item.pk}",
                )
                if coupon_obj and discount > 0:
                    _increment_coupon_usage(coupon_obj)

                if price > 0:
                    entry = debit(
                        wallet=wallet, amount=price, entry_type=LedgerEntry.Type.PURCHASE,
                        ref=f"order:{order.public_id}", note=f"Purchase: {item.plan}",
                    )
                    order.ledger_entry = entry
                order.status = Order.Status.PAID
                _assign_invoice_number(order)

                subscription = None
                if item.plan.interval != Plan.Interval.NONE:
                    subscription = _create_subscription(customer, item.plan, order, duration_multiplier=item.duration_multiplier)
                    order.subscription = subscription

                order.save(update_fields=["ledger_entry", "status", "subscription", "invoice_number", "updated_at"])

                grants = _provision_order(order, subscription=subscription)
                _record_seller_earning(order)
                emit("order.paid", customer_id=customer.pk, order_id=order.pk, plan_name=str(item.plan))

                grants_all.extend(grants)

            cart.items.filter(pk__in=checked_out_ids).delete()

        return cart_checkout, grants_all, None

    # Shortfall — one combined TopUp funds every pending Order under this CartCheckout.
    if not payment_method:
        raise CartPaymentMethodRequiredError("A payment_method is required when the wallet balance is insufficient.")

    shortfall = total - wallet.balance
    from apps.billing.services import initiate_topup

    # Everything here is one transaction: the pending orders, the combined TopUp, the
    # gateway call, and clearing the cart. If the gateway is unavailable initiate_topup
    # raises (SumopodError) and the whole thing rolls back — the buyer keeps their cart
    # and no half-finished orders are left behind.
    with transaction.atomic():
        cart_checkout = CartCheckout.objects.create(customer=customer)
        for item, price, discount, coupon_obj, _base in lines:
            Order.objects.create(
                customer=customer,
                plan=item.plan,
                amount=price,
                discount=discount,
                coupon=coupon_obj if discount > 0 else None,
                status=Order.Status.PENDING,
                duration_multiplier=item.duration_multiplier,
                cart_checkout=cart_checkout,
                idempotency_key=f"cart:{cart.pk}:item:{item.pk}",
            )

        topup, payment_url = initiate_topup(
            customer=customer, amount=shortfall, payment_method=payment_method or "QRIS",
            callback_url=callback_url, return_url=return_url, gateway_client=gateway_client,
        )
        topup.cart_checkout = cart_checkout
        topup.save(update_fields=["cart_checkout", "updated_at"])

        cart.items.filter(pk__in=checked_out_ids).delete()

    return cart_checkout, [], payment_url


def complete_cart_checkout(cart_checkout: CartCheckout) -> list:
    """Finish every pending Order under a CartCheckout once its funding TopUp is
    credited — mirrors apps.billing.checkout.complete_pending_order, looped.
    """
    from apps.billing.checkout import complete_pending_order

    grants = []
    for order in cart_checkout.orders.filter(status=Order.Status.PENDING):
        grants.extend(complete_pending_order(order))
    cart_checkout.status = CartCheckout.Status.COMPLETED
    cart_checkout.save(update_fields=["status", "updated_at"])
    return grants
