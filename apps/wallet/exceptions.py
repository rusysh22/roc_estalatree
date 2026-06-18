"""Wallet domain exceptions."""


class InsufficientBalance(Exception):
    """Raised when the wallet balance is insufficient to cover the requested debit."""
