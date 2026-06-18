"""Wallet signals: auto-provision a Wallet when a Customer is created (H3)."""
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="accounts.Customer")
def create_wallet_for_customer(sender, instance, created, **kwargs):
    """Every Customer gets exactly one Wallet, created atomically on their first save."""
    if created:
        from apps.wallet.models import Wallet

        Wallet.objects.get_or_create(customer=instance)
