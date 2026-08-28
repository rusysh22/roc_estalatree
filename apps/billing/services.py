"""Billing service layer — TopUp initiation, webhook processing, safety-net.

Payment gateway: Sumopod (see docs/DECISIONS.md — replaced Duitku).

Money rules:
- Wallet is ONLY credited through wallet/services.py credit().
- refs namespaced: topup:<public_id>, bonus:<public_id>
- Every credit call is idempotent — safe to retry.
- Webhook processing is guarded by PaymentWebhook.idempotency_key (unique).
- Bonus credit lives inside the same atomic block as the topup credit (H2).
- Webhook signature/token verification happens in the view; process_webhook_payload
  trusts the payload it receives.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import PaymentWebhook, TopUp
from apps.wallet.models import LedgerEntry
from apps.wallet.services import credit

logger = logging.getLogger(__name__)

# Must match expires_in_hours sent to Sumopod in create_payment() (24h max).
TOPUP_EXPIRY_MINUTES = 1440  # 24 hours


class TopUpNotFoundError(Exception):
    """Raised when a webhook references a TopUp that doesn't exist locally (M3)."""


# ── Top-up initiation ─────────────────────────────────────────────────────────

def initiate_topup(
    customer,
    amount: int,
    *,
    payment_method: str = "QRIS",
    bonus: int = 0,
    callback_url: str = "",
    return_url: str,
    gateway_client=None,
) -> tuple[TopUp, str]:
    """Create a pending TopUp and request a Sumopod payment link.

    Returns (topup, payment_url).
    The wallet is NOT credited here — only on confirmed webhook receipt.
    ``callback_url`` is accepted for backwards compatibility but unused: Sumopod
    webhooks are configured once in the dashboard, not per request.
    Raises ValueError for non-positive amounts.
    Raises SumopodError if the gateway call fails (TopUp created but gateway_ref empty).
    """
    if amount <= 0:
        raise ValueError(f"Top-up amount must be positive, got {amount!r}")
    if bonus < 0:
        raise ValueError(f"Bonus must be non-negative, got {bonus!r}")

    topup = TopUp.objects.create(
        customer=customer, amount=amount, bonus=bonus, gateway=TopUp.Gateway.SUMOPOD
    )

    if gateway_client is None:
        from apps.billing.sumopod import SumopodClient
        gateway_client = SumopodClient.from_settings()

    result = gateway_client.create_payment(
        order_id=topup.public_id,
        amount=amount,
        product_details=f"Top-up Rp{amount:,}",
        email=customer.user.email,
        success_url=return_url,
        cancel_url=return_url,
        payment_method_type_code=payment_method or "QRIS",
    )

    topup.gateway_ref = result.payment_id
    topup.gateway_fee = result.fee or 0
    topup.save(update_fields=["gateway_ref", "gateway_fee", "updated_at"])
    return topup, result.payment_url


# ── Shared apply helper ───────────────────────────────────────────────────────

def _apply_topup_success(topup: TopUp) -> bool:
    """Credit the wallet for a confirmed-paid TopUp. Idempotent.

    H2: bonus credit is inside the same atomic block as the topup credit —
    either both happen or neither (atomicity). The bonus:<id> ref keeps it
    idempotent on retries.

    ADR-015: if the TopUp has a linked checkout_order, complete it after
    the TopUp transaction commits (separate atomic — debit from newly funded wallet).
    Extended for carts: a TopUp funding a multi-item CartCheckout completes every
    pending Order under it the same way.

    Returns True if credit was applied, False if TopUp was already PAID.
    """
    checkout_order = None
    cart_checkout = None
    customer = None
    with transaction.atomic():
        locked = TopUp.objects.select_for_update().get(pk=topup.pk)
        if locked.status == TopUp.Status.PAID:
            return False

        customer = locked.customer  # captured for post-commit actions
        wallet = locked.customer.wallet

        topup_entry = credit(
            wallet=wallet,
            amount=locked.amount,
            entry_type=LedgerEntry.Type.TOPUP,
            ref=f"topup:{locked.public_id}",
            note=f"Sumopod top-up {locked.gateway_ref or locked.public_id}",
        )

        if locked.bonus > 0:
            credit(
                wallet=wallet,
                amount=locked.bonus,
                entry_type=LedgerEntry.Type.BONUS,
                ref=f"bonus:{locked.public_id}",
                note=f"Top-up promotional bonus for {locked.public_id}",
            )

        locked.ledger_entry = topup_entry
        locked.status = TopUp.Status.PAID
        locked.save(update_fields=["status", "ledger_entry", "updated_at"])

        # Emit after commit — handler dispatches notification tasks
        from apps.core.events import emit
        emit("topup.paid", customer_id=locked.customer_id, amount=locked.amount, bonus=locked.bonus)

        # Capture references before the atomic block exits
        if locked.checkout_order_id:
            checkout_order = locked.checkout_order
        if locked.cart_checkout_id:
            cart_checkout = locked.cart_checkout

    # ADR-015: complete the linked checkout order after TopUp credit commits
    if checkout_order is not None:
        from apps.billing.checkout import complete_pending_order
        complete_pending_order(checkout_order)

    if cart_checkout is not None:
        from apps.billing.cart_service import complete_cart_checkout
        complete_cart_checkout(cart_checkout)

    # Phase 6: wallet funded — attempt renewal for any GRACE subscriptions
    if customer is not None:
        from apps.billing.subscription_service import try_renew_grace_subscriptions
        try_renew_grace_subscriptions(customer)

    return True


# ── Webhook processing ────────────────────────────────────────────────────────

COMPLETED_EVENT = "payment.completed"
FAILED_EVENTS = {"payment.failed": TopUp.Status.FAILED, "payment.expired": TopUp.Status.EXPIRED}


def process_webhook_payload(
    gateway: str,
    idempotency_key: str,
    payload: dict,
    *,
    gateway_client=None,
) -> PaymentWebhook:
    """Record and process a verified Sumopod webhook.

    The webhook view is responsible for signature/token verification — by the time
    the payload reaches here it is trusted.

    Idempotent: same idempotency_key → returns existing record, no double-credit.
    Raises ValueError on an unparseable payload.
    Raises TopUpNotFoundError when no TopUp matches the order ID (M3 → 500).
    """
    event_type = str(payload.get("event_type", ""))
    data = payload.get("data") or {}
    order_id = str(data.get("order_id", ""))

    try:
        amount = int(float(data.get("amount", 0)))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Invalid amount in webhook payload: {data.get('amount')!r}"
        ) from exc

    # With fee passthrough enabled the customer pays `amount` (gross) while the
    # merchant receives `net_amount` — which equals what we requested. Accept
    # either against the local record in the M1 cross-check below.
    try:
        net_amount = int(float(data.get("net_amount", 0)))
    except (ValueError, TypeError):
        net_amount = 0

    # ── Idempotency gate (savepoint so IntegrityError doesn't abort outer tx) ──
    try:
        with transaction.atomic():
            webhook = PaymentWebhook.objects.create(
                idempotency_key=idempotency_key,
                gateway=gateway,
                payload=payload,
            )
    except IntegrityError:
        webhook = PaymentWebhook.objects.get(idempotency_key=idempotency_key)
        logger.info("Duplicate webhook ignored: %s", idempotency_key)
        return webhook

    # ── Test / unknown events — record only ───────────────────────────────────
    if event_type == "payment.test":
        logger.info("Sumopod test webhook received (%s)", idempotency_key)
        PaymentWebhook.objects.filter(pk=webhook.pk).update(processed_at=timezone.now())
        webhook.refresh_from_db()
        return webhook

    if event_type not in FAILED_EVENTS and event_type != COMPLETED_EVENT:
        logger.warning("Sumopod webhook: unhandled event_type=%s order=%s", event_type, order_id)
        return webhook

    # ── Find the TopUp ────────────────────────────────────────────────────────
    try:
        topup = TopUp.objects.get(public_id=order_id)
    except TopUp.DoesNotExist:
        # M3: raise so the view returns 500 — lets Sumopod retry (race/lag plausible).
        logger.error(
            "Sumopod webhook: no TopUp found for order_id=%s — will retry", order_id
        )
        raise TopUpNotFoundError(f"No TopUp found for order_id={order_id!r}")

    # ── Failure / expiry events ──────────────────────────────────────────────
    if event_type in FAILED_EVENTS:
        new_status = FAILED_EVENTS[event_type]
        updated = TopUp.objects.filter(
            pk=topup.pk, status=TopUp.Status.PENDING
        ).update(status=new_status)
        if updated:
            logger.info("TopUp %s marked %s via webhook %s", topup.public_id, new_status, idempotency_key)
        PaymentWebhook.objects.filter(pk=webhook.pk).update(processed_at=timezone.now())
        webhook.refresh_from_db()
        return webhook

    # ── payment.completed — M1 amount cross-check, then credit ───────────────
    if topup.amount not in (amount, net_amount):
        # M1: do not credit; leave processed_at=None so System Health can surface it.
        logger.error(
            "Sumopod webhook amount mismatch: order=%s amount=%s net_amount=%s expected=%s — not crediting",
            order_id, amount, net_amount, topup.amount,
        )
        return webhook

    applied = _apply_topup_success(topup)
    if applied:
        logger.info("TopUp %s credited via webhook %s", topup.public_id, idempotency_key)

    PaymentWebhook.objects.filter(pk=webhook.pk).update(processed_at=timezone.now())
    webhook.refresh_from_db()
    return webhook


# ── Safety-net polling ────────────────────────────────────────────────────────

def recheck_topup_status(topup: TopUp, *, gateway_client=None) -> None:
    """Safety-net for a single pending TopUp whose webhook never arrived.

    Sumopod exposes no transaction-status endpoint (see apps/billing/sumopod.py),
    so this can only expire TopUps that have sat PENDING past TOPUP_EXPIRY_MINUTES.
    The authoritative outcome for a real payment comes from the Sumopod webhook
    (payment.completed / payment.failed / payment.expired).
    """
    topup.refresh_from_db()  # caller's instance may be stale
    if topup.status != TopUp.Status.PENDING:
        return

    expiry_time = topup.created_at + timedelta(minutes=TOPUP_EXPIRY_MINUTES)
    if timezone.now() > expiry_time:
        updated = TopUp.objects.filter(
            pk=topup.pk, status=TopUp.Status.PENDING
        ).update(status=TopUp.Status.EXPIRED)
        if updated:
            logger.info(
                "Safety-net: TopUp %s marked EXPIRED (past %d min window)",
                topup.public_id,
                TOPUP_EXPIRY_MINUTES,
            )
