"""Checkout service — balance debit, order creation, provisioning dispatch.

Money rules:
- Wallet is ONLY debited through wallet/services.py debit().
- Order ref namespaced: order:<public_id>
- checkout() is idempotent via checkout_key (maps to Order.idempotency_key).

Flow:
  FREE  → Order(PAID, amount=0) [atomic: create + provision] → grants
  PAID, balance >= price → [atomic: debit + Order(PAID) + subscription + provision] → grants
  PAID, balance <  price → Order(PENDING) + TopUp(delta) → payment_url
  CONTACT → raises ContactPlanError

H1 (review): provisioning runs INSIDE the atomic block (pure-DB provisioners only).
  If a provisioner raises, the debit and Order status change roll back atomically.
  Phase 5+: external provisioners must use async fulfillment + idempotent retry.

See ADR-015 for top-up-and-buy design.
"""
import logging

from dateutil.relativedelta import relativedelta
from django.db import IntegrityError, transaction
from django.utils import timezone

from django.db.models import Max

from apps.billing.models import Order, Subscription
from apps.catalog.models import Plan, Product
from apps.core.events import emit
from apps.provisioning.models import Grant
from apps.wallet.exceptions import InsufficientBalance
from apps.wallet.models import LedgerEntry
from apps.wallet.services import debit

logger = logging.getLogger(__name__)


def _record_seller_earning(order) -> None:
    """Create SellerEarning for a paid order. Must be called inside transaction.atomic()."""
    try:
        from apps.billing.models import SellerEarning
        from apps.core.models import Setting
        seller = order.plan.product.seller
        if seller is None:
            return
        gross = order.amount
        rate = seller.commission_rate or 0
        commission = gross * rate // 100
        SellerEarning.objects.get_or_create(
            order=order,
            defaults={"seller": seller, "gross": gross, "commission": commission, "net": gross - commission},
        )
    except Exception:
        logger.exception("Failed to record seller earning for order %s", order.pk)


class ContactPlanError(Exception):
    """Contact-type plans cannot be purchased via checkout."""


class CheckoutIdempotencyError(Exception):
    """checkout_key was already used by a different customer/plan."""


class CouponLimitError(Exception):
    """Coupon usage_limit reached at the moment of atomic increment (concurrent checkout)."""


def _assign_invoice_number(order: Order) -> None:
    """Assign the next sequential invoice number. Must be called inside transaction.atomic()."""
    if order.invoice_number:
        return
    last = Order.objects.select_for_update().filter(
        invoice_number__isnull=False
    ).aggregate(Max("invoice_number"))["invoice_number__max"] or 0
    order.invoice_number = last + 1


# ── Internal helpers ──────────────────────────────────────────────────────────

def _create_subscription(customer, plan: Plan, order: Order) -> Subscription:
    """Create and return a Subscription for a recurring plan."""
    if plan.interval == Plan.Interval.MONTHLY:
        period_end = timezone.now() + relativedelta(months=1)
    elif plan.interval == Plan.Interval.YEARLY:  # LOW: explicit branch
        period_end = timezone.now() + relativedelta(years=1)
    else:
        raise ValueError(f"Cannot create subscription for interval {plan.interval!r}")
    return Subscription.objects.create(
        customer=customer,
        plan=plan,
        status=Subscription.Status.ACTIVE,
        current_period_end=period_end,
    )


def _provision_order(order: Order, *, subscription=None) -> list[Grant]:
    """Dispatch all deliverables for a paid order.

    H1: must be called INSIDE a transaction.atomic() so that a provisioner
    failure rolls back the debit and Order status change.
    H2: subscription passed through so Grant.subscription is set for recurring plans.
    """
    from apps.provisioning.registry import get as get_provisioner

    grants = []
    for deliverable in order.plan.deliverables.all():
        provisioner = get_provisioner(deliverable.type)
        grant = provisioner.provision(order, deliverable, subscription=subscription)
        grants.append(grant)
    return grants


# ── Top-up-and-buy completion (called from billing/services.py) ──────────────

def complete_pending_order(order: Order) -> list[Grant]:
    """Debit wallet and fulfill a pending Order after its funding TopUp is credited.

    Idempotent: if order is already PAID, returns empty list.
    Called from _apply_topup_success (ADR-015).

    M2 (review): if the customer spent the credited balance before this debit
    runs, InsufficientBalance is caught and logged. The Order stays PENDING —
    recoverable by Phase 6 support/job. Balance is not lost.
    """
    try:
        with transaction.atomic():
            locked = Order.objects.select_for_update().get(pk=order.pk)
            if locked.status != Order.Status.PENDING:
                logger.info(
                    "complete_pending_order: order %s already %s — skipping",
                    locked.public_id, locked.status,
                )
                return []

            entry = debit(
                wallet=locked.customer.wallet,
                amount=locked.amount,
                entry_type=LedgerEntry.Type.PURCHASE,
                ref=f"order:{locked.public_id}",
                note=f"Purchase: {locked.plan}",
            )
            locked.ledger_entry = entry
            locked.status = Order.Status.PAID
            _assign_invoice_number(locked)

            if locked.coupon_id and locked.discount:
                from django.db.models import F, Q
                from apps.billing.models import Coupon as CouponModel
                CouponModel.objects.filter(
                    Q(usage_limit=0) | Q(used_count__lt=F("usage_limit")),
                    pk=locked.coupon_id,
                ).update(used_count=F("used_count") + 1)

            subscription = None
            if locked.plan.interval != Plan.Interval.NONE:
                subscription = _create_subscription(locked.customer, locked.plan, locked)
                locked.subscription = subscription

            locked.save(update_fields=["ledger_entry", "status", "subscription", "invoice_number", "updated_at"])

            # H1: provision inside atomic — failure rolls back debit + PAID
            grants = _provision_order(locked, subscription=subscription)
            _record_seller_earning(locked)
            emit("order.paid", customer_id=locked.customer_id, order_id=locked.pk,
                 plan_name=str(locked.plan))

        return grants

    except InsufficientBalance:
        # M2: race — balance spent between TopUp credit and this debit.
        # Order stays PENDING (no money lost); Phase 6 job can retry or support can refund TopUp.
        logger.error(
            "complete_pending_order: InsufficientBalance for order %s after TopUp credit — "
            "Order stays PENDING; manual resolution required",
            order.pk,
        )
        return []


# ── Main checkout entrypoint ──────────────────────────────────────────────────

def checkout(
    customer,
    plan: Plan,
    checkout_key: str,
    *,
    coupon=None,
    price_override: int | None = None,
    custom_fields: dict | None = None,
    duitku_client=None,
    callback_url: str,
    return_url: str,
) -> tuple[Order, list[Grant], str | None]:
    """Purchase a plan for a customer.

    Args:
        customer:     accounts.Customer instance.
        plan:         catalog.Plan to purchase.
        checkout_key: Caller-supplied idempotency key — same key returns same Order.
        duitku_client: Injected for testing; omit in production.
        callback_url: Duitku webhook callback URL (only used when TopUp is needed).
        return_url:   Browser redirect URL after payment (only used when TopUp needed).

    Returns:
        (order, grants, payment_url)
        payment_url is None when fulfilled from balance (or free plan).
        grants is [] when a TopUp is needed (order remains PENDING until webhook).

    Raises:
        ContactPlanError: plan's product is contact-type.
        CheckoutIdempotencyError: checkout_key already used for a different order.
    """
    product = plan.product

    if product.type == Product.Type.CONTACT:
        raise ContactPlanError(
            f"Plan {plan.pk!r} belongs to a contact-type product — "
            "direct checkout is not available. Use the WhatsApp contact flow instead."
        )

    # ── Idempotency: return existing order for same key ───────────────────────
    existing = Order.objects.filter(idempotency_key=checkout_key).first()
    if existing:
        if existing.customer_id != customer.pk or existing.plan_id != plan.pk:
            raise CheckoutIdempotencyError(
                f"checkout_key {checkout_key!r} was already used for a different order"
            )
        # LOW: precise grant lookup via Grant.order (no plan-conflation)
        existing_grants = list(Grant.objects.filter(order=existing).order_by("-created_at"))
        return existing, existing_grants, None

    # ── FREE plan (M1 + H1: IntegrityError guard + provision inside atomic) ──
    if plan.price == 0 or product.type == Product.Type.FREE:
        with transaction.atomic():
            try:
                order = Order.objects.create(
                    customer=customer,
                    plan=plan,
                    amount=0,
                    status=Order.Status.PAID,
                    idempotency_key=checkout_key,
                )
            except IntegrityError:
                # M1: concurrent same-key race
                order = Order.objects.get(idempotency_key=checkout_key)
                grants = list(Grant.objects.filter(order=order).order_by("-created_at"))
                return order, grants, None

            # H1: provision inside atomic — KeyError rolls back Order creation
            grants = _provision_order(order, subscription=None)
            _record_seller_earning(order)
            emit("order.paid", customer_id=order.customer_id, order_id=order.pk,
                 plan_name=str(order.plan))

        return order, grants, None

    # ── Paid plan — determine base price (PWYW or fixed) ─────────────────────
    if price_override is not None and plan.pwyw:
        base_price = max(int(price_override), plan.min_price or 0)
    else:
        base_price = plan.price

    # ── Apply coupon discount ─────────────────────────────────────────────────
    discount = 0
    if coupon is not None:
        valid, _ = coupon.is_valid_for(plan)
        if valid:
            discount = coupon.compute_discount(base_price)

    effective_price = max(0, base_price - discount)

    # ── Paid plan — check balance ─────────────────────────────────────────────
    wallet = customer.wallet
    wallet.refresh_from_db()

    if wallet.balance >= effective_price:
        # Sufficient balance — debit and fulfill atomically (H1)
        with transaction.atomic():
            try:
                order = Order.objects.create(
                    customer=customer,
                    plan=plan,
                    amount=effective_price,
                    discount=discount,
                    coupon=coupon if discount > 0 else None,
                    status=Order.Status.PENDING,
                    idempotency_key=checkout_key,
                    custom_fields=custom_fields or {},
                )
            except IntegrityError:
                order = Order.objects.get(idempotency_key=checkout_key)
                grants = list(Grant.objects.filter(order=order).order_by("-created_at"))
                return order, grants, None

            if coupon is not None and discount > 0:
                from django.db.models import F, Q
                from apps.billing.models import Coupon as CouponModel
                updated = CouponModel.objects.filter(
                    Q(usage_limit=0) | Q(used_count__lt=F("usage_limit")),
                    pk=coupon.pk,
                ).update(used_count=F("used_count") + 1)
                if not updated and coupon.usage_limit > 0:
                    raise CouponLimitError("Coupon usage limit reached.")

            if effective_price > 0:
                entry = debit(
                    wallet=wallet,
                    amount=effective_price,
                    entry_type=LedgerEntry.Type.PURCHASE,
                    ref=f"order:{order.public_id}",
                    note=f"Purchase: {plan}",
                )
                order.ledger_entry = entry

            order.status = Order.Status.PAID
            _assign_invoice_number(order)

            # M3: link Order ↔ Subscription; H2: pass subscription to provisioner
            subscription = None
            if plan.interval != Plan.Interval.NONE:
                subscription = _create_subscription(customer, plan, order)
                order.subscription = subscription

            order.save(update_fields=["ledger_entry", "status", "subscription", "invoice_number", "updated_at"])

            # H1: provision inside atomic — failure rolls back debit + PAID
            grants = _provision_order(order, subscription=subscription)
            _record_seller_earning(order)
            emit("order.paid", customer_id=order.customer_id, order_id=order.pk,
                 plan_name=str(order.plan))

        return order, grants, None

    else:
        # Insufficient balance — initiate TopUp for the delta, link to pending Order
        delta = effective_price - wallet.balance

        with transaction.atomic():
            try:
                order = Order.objects.create(
                    customer=customer,
                    plan=plan,
                    amount=effective_price,
                    discount=discount,
                    coupon=coupon if discount > 0 else None,
                    status=Order.Status.PENDING,
                    idempotency_key=checkout_key,
                    custom_fields=custom_fields or {},
                )
            except IntegrityError:
                order = Order.objects.get(idempotency_key=checkout_key)
                return order, [], None

        from apps.billing.services import initiate_topup

        topup, payment_url = initiate_topup(
            customer=customer,
            amount=delta,
            callback_url=callback_url,
            return_url=return_url,
            duitku_client=duitku_client,
        )
        topup.checkout_order = order
        topup.save(update_fields=["checkout_order", "updated_at"])

        return order, [], payment_url
