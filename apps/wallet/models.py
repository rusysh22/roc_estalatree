"""Wallet models: Wallet (balance) and LedgerEntry (immutable, double-entry-style).

Money rules (CONVENTIONS.md):
- Whole IDR integer only (PositiveBigIntegerField for balance, BigIntegerField for amounts).
- LedgerEntry is NEVER updated or deleted — enforced here and in Django Admin.
- Wallet.balance invariant: balance == SUM(ledger entries) for this wallet.
- All mutations go through wallet/services.py, never direct field assignment.
"""
from django.db import models

from apps.core.models import TimestampedModel


class Wallet(TimestampedModel):
    """One wallet per customer. Balance is the platform's liability to the customer."""

    customer = models.OneToOneField(
        "accounts.Customer", on_delete=models.CASCADE, related_name="wallet"
    )
    balance = models.PositiveBigIntegerField(default=0)

    def __str__(self) -> str:
        return f"Wallet({self.customer}) Rp{self.balance:,}"


class LedgerEntry(models.Model):
    """Immutable ledger record. Never update or delete — enforced at model level + Admin."""

    class Type(models.TextChoices):
        TOPUP = "topup", "Top-up"
        PURCHASE = "purchase", "Purchase"
        RENEWAL = "renewal", "Renewal"
        REFUND = "refund", "Refund"
        ADJUSTMENT = "adjustment", "Adjustment"
        BONUS = "bonus", "Bonus"

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="entries")
    type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.BigIntegerField()  # positive = credit, negative = debit
    balance_after = models.PositiveBigIntegerField()
    ref = models.CharField(max_length=200, unique=True)  # idempotency key
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "created_at"]),
            # L1 fix: ref is unique=True so no separate Index needed
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise TypeError("LedgerEntry records are immutable — updates are not allowed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("LedgerEntry records are immutable — deletion is not allowed.")

    def __str__(self) -> str:
        sign = "+" if self.amount >= 0 else ""
        return f"[{self.type}] {sign}Rp{self.amount:,} → Rp{self.balance_after:,} ({self.ref})"