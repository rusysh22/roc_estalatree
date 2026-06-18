"""Checkout service — balance debit, order creation, provisioning dispatch.

Money rules:
- Wallet is ONLY debited through wallet/services.py debit().
- Order ref namespaced: order:<public_id>
- checkout() is idempotent via checkout_key (maps to Order.idempotency_key).

Flow:
  FREE  → Order(PAID, amount=0) → provision → grants
  PAID, balance >= price → debit → Order(PAID) → [subscription] → provision → grants
  PAID, balance <  price → TopUp(delta) + Order(PENDING, linked) → payment_url
  CONTACT → raises ContactPlanError

See ADR-015 for top-up-and-buy design.
"""
import logging

from dateutil.relativedelta import relativedelta
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import Order, Subscription
from apps.catalog.models import Plan, Product
from apps.provisioning.models import Grant
from apps.wallet.models import LedgerEntry
from apps.wallet.services import debit

logger = logging.getLogger(__name__)


class ContactPlanError(Exception):
    """Contact-type plans cannot be purchased via checkout."""


class CheckoutIdempotencyError(Exception):
    """checkout_key was already used by a different customer/plan."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _create_subscription(customer, plan: Plan, order: Order) -> Subscription:
    if plan.interval == Plan.Interval.MONTHLY:
        period_end = timezone.now() + relativedelta(months=1)
    else:
        period_end = timezone.now() + relativedelta(years=1)
    return Subscription.objects.create(
        customer=customer,
        plan=plan,
        status=Subscription.Status.ACTIVE,
        current_period_end=period_end,
    )


def _provision_order(order: Order) -> list[Grant]:
    """Dispatch all deliverables for a paid order."""
    from apps.provisioning.registry import get as get_provisioner

    grants = []
    for deliverable in order.plan.deliverables.all():
        provisioner = get_provisioner(deliverable.type)
        grant = provisioner.provision(order, deliverable)
        grants.append(grant)
    return grants


def _fulfill_paid_order(order: Order) -> list[Grant]:
    """Create subscription (if recurring) and provision. Call after Order is PAID."""
    plan = order.plan
    if plan.interval != Plan.Interval.NONE:
        _create_subscription(order.customer, plan, order)
    return _provision_order(order)


# ── Top-up-and-buy completion (called from billing/services.py) ──────────────

def complete_pending_order(order: Order) -> list[Grant]:
    """Debit wallet and fulfill a pending Order after its funding TopUp is credited.

    Idempotent: if order is already PAID, returns empty list.
    Called from _apply_topup_success (ADR-015).
    """
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status != Order.Status.PENDING:
            logger.info("complete_pending_order: order %s already %s", locked.public_id, locked.status)
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
        locked.save(update_fields=["ledger_entry", "status", "updated_at"])

    return _fulfill_paid_order(locked)


# ── Main checkout entrypoint ──────────────────────────────────────────────────

def checkout(
    customer,
    plan: Plan,
    checkout_key: str,
    *,
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
        existing_grants = list(
            Grant.objects.filter(
                customer=customer,
                deliverable__plan=plan,
            ).order_by("-created_at")
        )
        return existing, existing_grants, None

    # ── FREE plan ─────────────────────────────────────────────────────────────
    if plan.price == 0 or product.type == Product.Type.FREE:
        order = Order.objects.create(
            customer=customer,
            plan=plan,
            amount=0,
            status=Order.Status.PAID,
            idempotency_key=checkout_key,
        )
        grants = _fulfill_paid_order(order)
        return order, grants, None

    # ── Paid plan — check balance ─────────────────────────────────────────────
    wallet = customer.wallet
    wallet.refresh_from_db()

    if wallet.balance >= plan.price:
        # Sufficient balance — debit and fulfill
        with transaction.atomic():
            try:
                order = Order.objects.create(
                    customer=customer,
                    plan=plan,
                    amount=plan.price,
                    status=Order.Status.PENDING,
                    idempotency_key=checkout_key,
                )
            except IntegrityError:
                # Race: another request created the order with same key
                order = Order.objects.get(idempotency_key=checkout_key)
                grants = list(Grant.objects.filter(customer=customer, deliverable__plan=plan).order_by("-created_at"))
                return order, grants, None

            entry = debit(
                wallet=wallet,
                amount=plan.price,
                entry_type=LedgerEntry.Type.PURCHASE,
                ref=f"order:{order.public_id}",
                note=f"Purchase: {plan}",
            )
            order.ledger_entry = entry
            order.status = Order.Status.PAID
            order.save(update_fields=["ledger_entry", "status", "updated_at"])

        grants = _fulfill_paid_order(order)
        return order, grants, None

    else:
        # Insufficient balance — initiate TopUp for the delta, link to pending Order
        delta = plan.price - wallet.balance

        with transaction.atomic():
            try:
                order = Order.objects.create(
                    customer=customer,
                    plan=plan,
                    amount=plan.price,
                    status=Order.Status.PENDING,
                    idempotency_key=checkout_key,
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
