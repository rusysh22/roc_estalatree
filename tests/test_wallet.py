"""Phase 2 — Wallet & Ledger tests.

Covers:
- balance == SUM(ledger) invariant
- credit / debit basic operations
- idempotency (same ref → same entry, no double-write)
- reject overdraw (InsufficientBalance)
- debit exact balance to zero
- LedgerEntry immutability at model level
- auto-create wallet on Customer creation (H3)
- concurrent credits (thread-safety via select_for_update)
"""
import threading

import pytest

from apps.wallet.exceptions import InsufficientBalance
from apps.wallet.models import LedgerEntry, Wallet
from apps.wallet.services import credit, debit
from tests.factories import CustomerFactory


# ── Helpers ──────────────────────────────────────────────────────────────────

def _balance_invariant(wallet: Wallet) -> bool:
    """Return True if wallet.balance matches SUM(ledger entries)."""
    wallet.refresh_from_db()
    total = sum(e.amount for e in wallet.entries.all())
    return wallet.balance == total


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def customer(db):
    return CustomerFactory()


@pytest.fixture
def wallet(customer):
    return customer.wallet


# ── Auto-create Wallet (H3) ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_wallet_auto_created_with_customer():
    """Creating a Customer triggers post_save signal; Wallet is auto-provisioned."""
    customer = CustomerFactory()
    assert Wallet.objects.filter(customer=customer).exists()
    assert customer.wallet.balance == 0


@pytest.mark.django_db
def test_wallet_is_one_to_one():
    """Only one wallet per customer — get_or_create on repeated signals is idempotent."""
    customer = CustomerFactory()
    # Simulate signal firing twice (shouldn't happen, but must be safe).
    Wallet.objects.get_or_create(customer=customer)
    assert Wallet.objects.filter(customer=customer).count() == 1


# ── Credit ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_credit_increases_balance(wallet):
    entry = credit(wallet, 50_000, LedgerEntry.Type.TOPUP, ref="topup-001")
    wallet.refresh_from_db()
    assert wallet.balance == 50_000
    assert entry.amount == 50_000
    assert entry.balance_after == 50_000
    assert entry.type == LedgerEntry.Type.TOPUP


@pytest.mark.django_db
def test_credit_multiple_entries(wallet):
    credit(wallet, 100_000, LedgerEntry.Type.TOPUP, ref="topup-a")
    credit(wallet, 25_000, LedgerEntry.Type.BONUS, ref="bonus-a")
    wallet.refresh_from_db()
    assert wallet.balance == 125_000
    assert _balance_invariant(wallet)


@pytest.mark.django_db
def test_credit_rejects_zero(wallet):
    with pytest.raises(ValueError):
        credit(wallet, 0, LedgerEntry.Type.TOPUP, ref="bad-zero")


@pytest.mark.django_db
def test_credit_rejects_negative(wallet):
    with pytest.raises(ValueError):
        credit(wallet, -100, LedgerEntry.Type.TOPUP, ref="bad-neg")


# ── Debit ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_debit_reduces_balance(wallet):
    credit(wallet, 100_000, LedgerEntry.Type.TOPUP, ref="topup-x")
    entry = debit(wallet, 30_000, LedgerEntry.Type.PURCHASE, ref="order-x")
    wallet.refresh_from_db()
    assert wallet.balance == 70_000
    assert entry.amount == -30_000
    assert entry.balance_after == 70_000
    assert _balance_invariant(wallet)


@pytest.mark.django_db
def test_debit_exact_balance_to_zero(wallet):
    credit(wallet, 50_000, LedgerEntry.Type.TOPUP, ref="topup-exact")
    debit(wallet, 50_000, LedgerEntry.Type.PURCHASE, ref="order-exact")
    wallet.refresh_from_db()
    assert wallet.balance == 0
    assert _balance_invariant(wallet)


@pytest.mark.django_db
def test_debit_raises_insufficient_balance(wallet):
    credit(wallet, 10_000, LedgerEntry.Type.TOPUP, ref="topup-small")
    with pytest.raises(InsufficientBalance):
        debit(wallet, 20_000, LedgerEntry.Type.PURCHASE, ref="order-too-big")
    wallet.refresh_from_db()
    assert wallet.balance == 10_000  # unchanged


@pytest.mark.django_db
def test_debit_insufficient_on_empty_wallet(wallet):
    with pytest.raises(InsufficientBalance):
        debit(wallet, 1, LedgerEntry.Type.PURCHASE, ref="order-empty")


@pytest.mark.django_db
def test_debit_rejects_zero(wallet):
    with pytest.raises(ValueError):
        debit(wallet, 0, LedgerEntry.Type.PURCHASE, ref="bad-zero-d")


# ── Idempotency ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_credit_idempotent(wallet):
    """Calling credit() twice with the same ref must not double-write."""
    e1 = credit(wallet, 50_000, LedgerEntry.Type.TOPUP, ref="idem-topup")
    e2 = credit(wallet, 50_000, LedgerEntry.Type.TOPUP, ref="idem-topup")
    assert e1.pk == e2.pk
    wallet.refresh_from_db()
    assert wallet.balance == 50_000
    assert LedgerEntry.objects.filter(ref="idem-topup").count() == 1


@pytest.mark.django_db
def test_debit_idempotent(wallet):
    """Calling debit() twice with the same ref must not double-write."""
    credit(wallet, 100_000, LedgerEntry.Type.TOPUP, ref="idem-base")
    e1 = debit(wallet, 40_000, LedgerEntry.Type.PURCHASE, ref="idem-order")
    e2 = debit(wallet, 40_000, LedgerEntry.Type.PURCHASE, ref="idem-order")
    assert e1.pk == e2.pk
    wallet.refresh_from_db()
    assert wallet.balance == 60_000
    assert LedgerEntry.objects.filter(ref="idem-order").count() == 1


# ── Balance invariant ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_balance_invariant_after_mixed_ops(wallet):
    credit(wallet, 200_000, LedgerEntry.Type.TOPUP, ref="inv-t1")
    credit(wallet, 50_000, LedgerEntry.Type.BONUS, ref="inv-b1")
    debit(wallet, 80_000, LedgerEntry.Type.PURCHASE, ref="inv-o1")
    debit(wallet, 30_000, LedgerEntry.Type.RENEWAL, ref="inv-r1")
    assert _balance_invariant(wallet)


# ── Immutability ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_ledger_entry_cannot_be_updated(wallet):
    entry = credit(wallet, 10_000, LedgerEntry.Type.TOPUP, ref="immut-u")
    entry.note = "tampered"
    with pytest.raises(TypeError):
        entry.save()


@pytest.mark.django_db
def test_ledger_entry_cannot_be_deleted(wallet):
    entry = credit(wallet, 10_000, LedgerEntry.Type.TOPUP, ref="immut-d")
    with pytest.raises(TypeError):
        entry.delete()


# ── Concurrency ───────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_concurrent_credits_are_serialised(wallet):
    """Ten concurrent credit calls must each write exactly once; final balance correct.

    MH2: select_for_update is a no-op on SQLite — skip on non-PostgreSQL.
    """
    from django.db import connection as _conn
    if _conn.vendor != "postgresql":
        pytest.skip("select_for_update is a no-op on SQLite; run on PostgreSQL only")

    errors = []
    threads = []

    def do_credit(n):
        try:
            from django.db import connection
            connection.close()  # each thread opens its own connection
            credit(wallet, 10_000, LedgerEntry.Type.TOPUP, ref=f"conc-{n}")
        except Exception as exc:
            errors.append(exc)

    for i in range(10):
        t = threading.Thread(target=do_credit, args=(i,))
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    wallet.refresh_from_db()
    assert wallet.balance == 100_000
    assert LedgerEntry.objects.filter(wallet=wallet).count() == 10
    assert _balance_invariant(wallet)


# ── Ref-match guards (MH1 / L2) ──────────────────────────────────────────────

@pytest.mark.django_db
def test_cross_operation_ref_reuse_raises(wallet):
    """Reusing a credit ref for a debit raises ValueError (direction mismatch).

    Uses ADJUSTMENT type for both calls so the direction check fires (not the type check).
    """
    credit(wallet, 100_000, LedgerEntry.Type.ADJUSTMENT, ref="adj:ref-x01")
    with pytest.raises(ValueError, match="credit"):
        debit(wallet, 50_000, LedgerEntry.Type.ADJUSTMENT, ref="adj:ref-x01")


@pytest.mark.django_db
def test_cross_wallet_ref_reuse_raises():
    """Reusing a ref on a different wallet raises ValueError (wallet mismatch)."""
    customer_a = CustomerFactory()
    customer_b = CustomerFactory()
    credit(customer_a.wallet, 50_000, LedgerEntry.Type.TOPUP, ref="topup:shared-ref")
    with pytest.raises(ValueError, match="wallet"):
        credit(customer_b.wallet, 50_000, LedgerEntry.Type.TOPUP, ref="topup:shared-ref")


@pytest.mark.django_db
def test_invalid_entry_type_rejected(wallet):
    """Unknown entry_type raises ValueError before any DB write (M1)."""
    with pytest.raises(ValueError, match="Invalid entry_type"):
        credit(wallet, 10_000, "FAKE_TYPE", ref="fake-type-ref")
    assert not LedgerEntry.objects.filter(ref="fake-type-ref").exists()


@pytest.mark.django_db(transaction=True)
def test_same_ref_concurrent_yields_one_entry(wallet):
    """Two concurrent credits with identical ref produce exactly one ledger entry (L2).

    MH2: skip on non-PostgreSQL.
    """
    from django.db import connection as _conn
    if _conn.vendor != "postgresql":
        pytest.skip("select_for_update is a no-op on SQLite; run on PostgreSQL only")

    credit(wallet, 100_000, LedgerEntry.Type.TOPUP, ref="conc-base-same")

    results: list = []
    errors: list = []

    def do_same_ref():
        try:
            from django.db import connection
            connection.close()
            entry = credit(wallet, 5_000, LedgerEntry.Type.BONUS, ref="conc-same-ref")
            results.append(entry.pk)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=do_same_ref) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    assert LedgerEntry.objects.filter(ref="conc-same-ref").count() == 1
    assert results[0] == results[1]
