"""Billing service layer — TopUp initiation, webhook processing, safety-net polling.

Money rules:
- Wallet is ONLY credited through wallet/services.py credit().
- ref namespacing: topup:<public_id>, bonus:<public_id>
- Every credit call is idempotent — safe to retry.
- Webhook processing is guarded by PaymentWebhook.idempotency_key (unique).
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import PaymentWebhook, TopUp
from apps.wallet.models import LedgerEntry
from apps.wallet.services import credit

logger = logging.getLogger(__name__)


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

    Returns True if the credit was applied, False if TopUp was already PAID.
    Uses select_for_update to prevent concurrent double-credit.
    """
    with transaction.atomic():
        locked = TopUp.objects.select_for_update().get(pk=topup.pk)
        if locked.status == TopUp.Status.PAID:
            return False

        wallet = locked.customer.wallet

        topup_entry = credit(
            wallet=wallet,
            amount=locked.amount,
            entry_type=LedgerEntry.Type.TOPUP,
            ref=f"topup:{locked.public_id}",
            note=f"Duitku top-up {locked.gateway_ref or locked.public_id}",
        )

        locked.ledger_entry = topup_entry
        locked.status = TopUp.Status.PAID
        locked.save(update_fields=["status", "ledger_entry", "updated_at"])

    # Bonus credited outside the topup lock (already idempotent via credit() ref).
    if topup.bonus > 0:
        credit(
            wallet=topup.customer.wallet,
            amount=topup.bonus,
            entry_type=LedgerEntry.Type.BONUS,
            ref=f"bonus:{topup.public_id}",
            note=f"Top-up promotional bonus for {topup.public_id}",
        )

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
    Raises ValueError on invalid signature — caller should return HTTP 400.
    """
    # ── Signature verification (before touching the DB) ───────────────────────
    if duitku_client is None:
        from apps.billing.duitku import DuitkuClient
        duitku_client = DuitkuClient.from_settings()

    merchant_code = payload.get("merchantCode", "")
    amount = int(payload.get("amount", 0))
    merchant_order_id = str(payload.get("merchantOrderId", ""))
    signature = payload.get("signature", "")
    result_code = str(payload.get("resultCode", ""))

    if not duitku_client.verify_webhook_signature(merchant_code, amount, merchant_order_id, signature):
        raise ValueError(
            f"Invalid Duitku webhook signature for order {merchant_order_id!r}"
        )

    # ── Idempotency gate ──────────────────────────────────────────────────────
    # Wrapped in a savepoint so IntegrityError doesn't abort the outer transaction.
    try:
        with transaction.atomic():
            webhook = PaymentWebhook.objects.create(
                idempotency_key=idempotency_key,
                gateway=gateway,
                payload=payload,
            )
    except IntegrityError:
        # Already recorded — fetch and return (idempotent no-op).
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

    # ── Apply credit ──────────────────────────────────────────────────────────
    try:
        topup = TopUp.objects.get(public_id=merchant_order_id)
    except TopUp.DoesNotExist:
        logger.error(
            "Duitku webhook: no TopUp found for merchantOrderId=%s", merchant_order_id
        )
        return webhook

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
        logger.info(
            "Safety-net: Duitku confirms payment for %s — applying credit", topup.public_id
        )
        _apply_topup_success(topup)
    elif status.is_failed:
        logger.info("Safety-net: Duitku reports failed for %s", topup.public_id)
        TopUp.objects.filter(pk=topup.pk, status=TopUp.Status.PENDING).update(
            status=TopUp.Status.FAILED
        )
    # is_pending → no action; task will retry on next run
