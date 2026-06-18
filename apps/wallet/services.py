"""Wallet service layer — the ONLY authorised path to mutate balances.

Rules (see docs/CONVENTIONS.md):
- Never update Wallet.balance directly outside this module.
- Every mutation is wrapped in transaction.atomic() + select_for_update().
- LedgerEntry.ref is an idempotency key: same ref → return existing entry, no-op.
- credit() amount must be > 0; debit() amount must be > 0 (service writes -amount).
- debit() raises InsufficientBalance when balance < amount.
"""
from django.db import transaction

from apps.wallet.exceptions import InsufficientBalance
from apps.wallet.models import LedgerEntry, Wallet


def credit(
    wallet: Wallet,
    amount: int,
    entry_type: str,
    ref: str,
    note: str = "",
) -> LedgerEntry:
    """Credit wallet by `amount` IDR. Returns the LedgerEntry.

    Idempotent: calling twice with the same `ref` returns the existing entry.
    Raises ValueError for non-positive amounts.
    """
    if amount <= 0:
        raise ValueError(f"credit amount must be positive, got {amount!r}")

    # Fast path: already processed (no lock needed for this read).
    existing = LedgerEntry.objects.filter(ref=ref).first()
    if existing is not None:
        return existing

    with transaction.atomic():
        locked = Wallet.objects.select_for_update().get(pk=wallet.pk)

        # Re-check inside lock to handle concurrent callers with the same ref.
        existing = LedgerEntry.objects.filter(ref=ref).first()
        if existing is not None:
            return existing

        new_balance = locked.balance + amount
        entry = LedgerEntry.objects.create(
            wallet=locked,
            type=entry_type,
            amount=amount,
            balance_after=new_balance,
            ref=ref,
            note=note,
        )
        locked.balance = new_balance
        locked.save(update_fields=["balance", "updated_at"])
        return entry


def debit(
    wallet: Wallet,
    amount: int,
    entry_type: str,
    ref: str,
    note: str = "",
) -> LedgerEntry:
    """Debit wallet by `amount` IDR. Returns the LedgerEntry.

    Idempotent: calling twice with the same `ref` returns the existing entry.
    Raises InsufficientBalance when balance < amount.
    Raises ValueError for non-positive amounts.
    """
    if amount <= 0:
        raise ValueError(f"debit amount must be positive, got {amount!r}")

    # Fast path: already processed (no lock needed for this read).
    existing = LedgerEntry.objects.filter(ref=ref).first()
    if existing is not None:
        return existing

    with transaction.atomic():
        locked = Wallet.objects.select_for_update().get(pk=wallet.pk)

        # Re-check inside lock to handle concurrent callers with the same ref.
        existing = LedgerEntry.objects.filter(ref=ref).first()
        if existing is not None:
            return existing

        if locked.balance < amount:
            raise InsufficientBalance(
                f"Balance Rp{locked.balance:,} is insufficient for debit of Rp{amount:,}"
            )

        new_balance = locked.balance - amount
        entry = LedgerEntry.objects.create(
            wallet=locked,
            type=entry_type,
            amount=-amount,  # negative = debit in ledger
            balance_after=new_balance,
            ref=ref,
            note=note,
        )
        locked.balance = new_balance
        locked.save(update_fields=["balance", "updated_at"])
        return entry
