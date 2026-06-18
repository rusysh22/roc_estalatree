"""Billing service layer — TopUp initiation, webhook processing, safety-net polling.

Money rules:
- Wallet is ONLY credited through wallet/services.py credit().
- refs namespaced: topup:<public_id>, bonus:<public_id>
- Every credit call is idempotent — safe to retry.
- Webhook processing is guarded by PaymentWebhook.idempotency_key (unique).
- Bonus credit lives inside the same atomic block as the topup credit (H2).
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import PaymentWebhook, TopUp
from apps.wallet.models import LedgerEntry
from apps.wallet.services import credit

logger = logging.getLogger(__name__)

# Must match expiryPeriod sent to Duitku in create_invoice().
TOPUP_EXPIRY_MINUTES = 1440  # 24 hours


class TopUpNotFoundError(Exception):
    """Raised when a Duitku webhook references a TopUp that doesn't exist locally (M3)."""


# ── Top-up initiation ─────────────────────────────────────────────────────────

def initiate_topup(
    customer,
    amount: int,
    *,
    bonus: int = 0,
    callback_url: str,
    return_url: str,
    duitku_client=None,
) -> tuple[TopUp, str]:
    """Create a pending TopUp and request a Duitku invoice.

    Returns (topup, payment_url).
    The wallet is NOT credited here — only on confirmed webhook receipt.
    Raises ValueError for non-positive amounts.
    Raises DuitkuError if the gateway call fails (TopUp created but gateway_ref empty).
    """
    if amount <= 0:
        raise ValueError(f"Top-up amount must be positive, got {amount!r}")
    if bonus < 0:
        raise ValueError(f"Bonus must be non-negative, got {bonus!r}")

    topup = TopUp.objects.create(customer=customer, amount=amount, bonus=bonus)

    if duitku_client is None:
        from apps.billing.duitku import DuitkuClient
        duitku_client = DuitkuClient.from_settings()

    result = duitku_client.create_invoice(
        merchant_order_id=topup.public_id,
        amount=amount,
        product_details=f"Top-up Rp{amount:,}",
        email=customer.user.email,
        callback_url=callback_url,
        return_url=return_url,
    )

    topup.gateway_ref = result.reference
    topup.save(update_fields=["gateway_ref", "updated_at"])
    return topup, result.payment_url


# ── Shared apply helper ───────────────────────────────────────────────────────

def _apply_topup_success(topup: TopUp) -> bool:
    """Credit the wallet for a confirmed-paid TopUp. Idempotent.

    H2: bonus credit is inside the same atomic block as the topup credit —
    either both happen or neither (atomicity). The bonus:<id> ref keeps it
    idempotent on retries.

    ADR-015: if the TopUp has a linked checkout_order, complete it after
    the TopUp transaction commits (separate atomic — debit from newly funded wallet).

    Returns True if credit was applied, False if TopUp was already PAID.
    """
    checkout_order = None
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
            note=f"Duitku top-up {locked.gateway_ref or locked.public_id}",
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

        # Capture checkout_order reference before the atomic block exits
        if locked.checkout_order_id:
            checkout_order = locked.checkout_order

    # ADR-015: complete the linked checkout order after TopUp credit commits
    if checkout_order is not None:
        from apps.billing.checkout import complete_pending_order
        complete_pending_order(checkout_order)

    # Phase 6: wallet funded — attempt renewal for any GRACE subscriptions
    if customer is not None:
        from apps.billing.subscription_service import try_renew_grace_subscriptions
        try_renew_grace_subscriptions(customer)

    return True


# ── Webhook processing ────────────────────────────────────────────────────────

def process_webhook_payload(
    gateway: str,
    idempotency_key: str,
    payload: dict,
    *,
    duitku_client=None,
) -> PaymentWebhook:
    """Verify, record, and process a Duitku payment webhook.

    Idempotent: same idempotency_key → returns existing record, no double-credit.
    Raises ValueError on invalid signature or unparseable amount.
    Raises TopUpNotFoundError when no TopUp matches the order ID (M3 → 500).
    """
    # ── Signature verification (before touching the DB) ───────────────────────
    if duitku_client is None:
        from apps.billing.duitku import DuitkuClient
        duitku_client = DuitkuClient.from_settings()

    merchant_code = str(payload.get("merchantCode", ""))
    merchant_order_id = str(payload.get("merchantOrderId", ""))
    result_code = str(payload.get("resultCode", ""))
    signature = str(payload.get("signature", ""))

    # LOW: defensive amount parsing — Duitku may send int or string
    try:
        amount = int(float(payload.get("amount", 0)))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Invalid amount in webhook payload: {payload.get('amount')!r}"
        ) from exc

    if not duitku_client.verify_webhook_signature(merchant_code, amount, merchant_order_id, signature):
        raise ValueError(
            f"Invalid Duitku webhook signature for order {merchant_order_id!r}"
        )

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

    # ── Non-success result ────────────────────────────────────────────────────
    if result_code != "00":
        logger.info(
            "Duitku webhook non-success: order=%s resultCode=%s",
            merchant_order_id,
            result_code,
        )
        return webhook

    # ── Find the TopUp ────────────────────────────────────────────────────────
    try:
        topup = TopUp.objects.get(public_id=merchant_order_id)
    except TopUp.DoesNotExist:
        # M3: raise so the view returns 500 — lets Duitku retry (race/lag plausible).
        logger.error(
            "Duitku webhook: no TopUp found for merchantOrderId=%s — will retry",
            merchant_order_id,
        )
        raise TopUpNotFoundError(
            f"No TopUp found for merchantOrderId={merchant_order_id!r}"
        )

    # ── M1: amount cross-check ─────────────────────────────────────────────────
    if amount != topup.amount:
        # M1: do not credit; leave processed_at=None so System Health can surface it.
        logger.error(
            "Duitku webhook amount mismatch: order=%s claimed=%s expected=%s — not crediting",
            merchant_order_id,
            amount,
            topup.amount,
        )
        return webhook

    # ── Apply credit ──────────────────────────────────────────────────────────
    applied = _apply_topup_success(topup)
    if applied:
        logger.info("TopUp %s credited via webhook %s", topup.public_id, idempotency_key)

    PaymentWebhook.objects.filter(pk=webhook.pk).update(processed_at=timezone.now())
    webhook.refresh_from_db()
    return webhook


# ── Safety-net polling ────────────────────────────────────────────────────────

def recheck_topup_status(topup: TopUp, *, duitku_client=None) -> None:
    """Poll Duitku for a single pending TopUp and apply if confirmed paid.

    Called by the Celery safety-net task for TopUps whose webhook never arrived.
    M1: cross-checks Duitku-reported amount against local record before crediting.
    M4: marks EXPIRED when still pending after TOPUP_EXPIRY_MINUTES.
    """
    topup.refresh_from_db()  # caller's instance may be stale
    if topup.status != TopUp.Status.PENDING:
        return

    if duitku_client is None:
        from apps.billing.duitku import DuitkuClient
        duitku_client = DuitkuClient.from_settings()

    try:
        status = duitku_client.check_transaction(topup.public_id)
    except Exception as exc:
        logger.warning("Duitku status check failed for %s: %s", topup.public_id, exc)
        return

    if status.is_success:
        # M1: cross-check amount when Duitku provides it
        if status.amount > 0 and status.amount != topup.amount:
            logger.error(
                "Safety-net amount mismatch: order=%s duitku=%s expected=%s — not crediting",
                topup.public_id,
                status.amount,
                topup.amount,
            )
            return
        logger.info(
            "Safety-net: Duitku confirms payment for %s — applying credit", topup.public_id
        )
        _apply_topup_success(topup)

    elif status.is_failed:
        logger.info("Safety-net: Duitku reports failed for %s", topup.public_id)
        TopUp.objects.filter(pk=topup.pk, status=TopUp.Status.PENDING).update(
            status=TopUp.Status.FAILED
        )

    else:
        # M4: still pending — mark EXPIRED if past the invoice expiry window
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
