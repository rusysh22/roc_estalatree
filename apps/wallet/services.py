"""Wallet service layer — the ONLY authorised path to mutate balances.

Rules (see docs/CONVENTIONS.md):
- Never update Wallet.balance directly outside this module.
- Every mutation is wrapped in transaction.atomic() + select_for_update().
- LedgerEntry.ref is an idempotency key: same ref → return existing entry, no-op.
- credit() amount must be > 0; debit() amount must be > 0 (service writes -amount).
- debit() raises InsufficientBalance when balance < amount.

Ref namespacing convention (MH1 — callers MUST follow this):
  top-up:     "topup:<topup.public_id>"
  order:      "order:<order.public_id>"
  renewal:    "renewal:<sub.pk>:<period_end_date>"
  refund:     "refund:<order.public_id>"
  adjustment: "adj:<reason>:<target_id>"
  bonus:      "bonus:<topup.public_id>"

Namespacing prevents accidental ref reuse across different operation types.
The service also guards defensively: if a ref is reused with mismatched wallet,
type, or direction, it raises ValueError immediately (silent money bug prevention).
"""
from django.db import IntegrityError, transaction

from apps.wallet.exceptions import InsufficientBalance
from apps.wallet.models import LedgerEntry, Wallet


def _validate_entry_type(entry_type: str) -> None:
    """Raise ValueError for unknown entry types (M1)."""
    if entry_type not in LedgerEntry.Type.values:
        raise ValueError(
            f"Invalid entry_type {entry_type!r}. Valid values: {LedgerEntry.Type.values}"
        )


def _check_idempotent_match(
    existing: LedgerEntry,
    wallet: Wallet,
    entry_type: str,
    expected_positive: bool,
) -> None:
    """Guard against silent money bugs when a ref is reused with different params (MH1).

    Raises ValueError if wallet, type, or amount direction do not match the original entry.
    """
    if existing.wallet_id != wallet.pk:
        raise ValueError(
            f"Idempotency ref {existing.ref!r} was previously recorded for wallet "
            f"{existing.wallet_id}, but caller passed wallet {wallet.pk}."
        )
    if existing.type != entry_type:
        raise ValueError(
            f"Idempotency ref {existing.ref!r} was previously recorded with type "
            f"{existing.type!r}, but caller requested {entry_type!r}."
        )
    actual_positive = existing.amount > 0
    if actual_positive != expected_positive:
        original = "credit" if actual_positive else "debit"
        requested = "credit" if expected_positive else "debit"
        raise ValueError(
            f"Idempotency ref {existing.ref!r} was previously recorded as a {original}, "
            f"but caller requested a {requested}."
        )


def credit(
    wallet: Wallet,
    amount: int,
    entry_type: str,
    ref: str,
    note: str = "",
) -> LedgerEntry:
    """Credit wallet by `amount` IDR. Returns the LedgerEntry.

    Idempotent: calling twice with the same `ref` returns the existing entry.
    Raises ValueError for non-positive amounts, invalid entry_type, or mismatched ref reuse.
    Raises ValueError if `ref` was previously used for a different wallet, type, or debit.

    Note: the caller's `wallet` instance is stale after this call —
    call wallet.refresh_from_db() if you need the updated balance.
    """
    if amount <= 0:
        raise ValueError(f"credit amount must be positive, got {amount!r}")
    _validate_entry_type(entry_type)

    # Fast path: already processed (no lock needed for this read).
    existing = LedgerEntry.objects.filter(ref=ref).first()
    if existing is not None:
        _check_idempotent_match(existing, wallet, entry_type, expected_positive=True)
        return existing

    with transaction.atomic():
        locked = Wallet.objects.select_for_update().get(pk=wallet.pk)

        # Re-check inside lock: handles concurrent callers with the same ref.
        existing = LedgerEntry.objects.filter(ref=ref).first()
        if existing is not None:
            _check_idempotent_match(existing, locked, entry_type, expected_positive=True)
            return existing

        new_balance = locked.balance + amount
        try:
            entry = LedgerEntry.objects.create(
                wallet=locked,
                type=entry_type,
                amount=amount,
                balance_after=new_balance,
                ref=ref,
                note=note,
            )
        except IntegrityError:
            # M2 backstop: ref inserted between re-check and create (extreme edge case).
            existing = LedgerEntry.objects.get(ref=ref)
            _check_idempotent_match(existing, locked, entry_type, expected_positive=True)
            return existing

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
    Raises InsufficientBalance when balance is insufficient to cover the debit.
    Raises ValueError for non-positive amounts, invalid entry_type, or mismatched ref reuse.
    Raises ValueError if `ref` was previously used for a different wallet, type, or credit.

    Note: the caller's `wallet` instance is stale after this call —
    call wallet.refresh_from_db() if you need the updated balance.
    """
    if amount <= 0:
        raise ValueError(f"debit amount must be positive, got {amount!r}")
    _validate_entry_type(entry_type)

    # Fast path: already processed (no lock needed for this read).
    existing = LedgerEntry.objects.filter(ref=ref).first()
    if existing is not None:
        _check_idempotent_match(existing, wallet, entry_type, expected_positive=False)
        return existing

    with transaction.atomic():
        locked = Wallet.objects.select_for_update().get(pk=wallet.pk)

        # Re-check inside lock: handles concurrent callers with the same ref.
        existing = LedgerEntry.objects.filter(ref=ref).first()
        if existing is not None:
            _check_idempotent_match(existing, locked, entry_type, expected_positive=False)
            return existing

        if locked.balance < amount:
            raise InsufficientBalance(
                f"Balance Rp{locked.balance:,} is insufficient for debit of Rp{amount:,}"
            )

        new_balance = locked.balance - amount
        try:
            entry = LedgerEntry.objects.create(
                wallet=locked,
                type=entry_type,
                amount=-amount,  # negative = debit in ledger
                balance_after=new_balance,
                ref=ref,
                note=note,
            )
        except IntegrityError:
            # M2 backstop: ref inserted between re-check and create (extreme edge case).
            existing = LedgerEntry.objects.get(ref=ref)
            _check_idempotent_match(existing, locked, entry_type, expected_positive=False)
            return existing

        locked.balance = new_balance
        locked.save(update_fields=["balance", "updated_at"])
        return entry
