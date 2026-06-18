"""Wallet domain exceptions."""


class InsufficientBalance(Exception):
    """Raised when a debit would take the wallet balance below zero."""
