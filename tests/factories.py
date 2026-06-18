"""Shared test factories using factory_boy.

Usage:
    from tests.factories import CustomerFactory, WalletFactory

Note: CustomerFactory triggers the post_save signal that auto-creates a Wallet.
Access it via `customer.wallet` rather than creating a separate WalletFactory instance.
"""
import factory

from apps.accounts.models import Customer, User
from apps.wallet.models import Wallet


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    is_active = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "testpass123")
        manager = cls._get_manager(model_class)
        return manager.create_user(*args, password=password, **kwargs)


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer

    user = factory.SubFactory(UserFactory)


class WalletFactory(factory.django.DjangoModelFactory):
    """Use this only when you need a wallet without a Customer (rare).

    In most tests, CustomerFactory auto-creates a wallet via post_save signal.
    """

    class Meta:
        model = Wallet
        django_get_or_create = ("customer",)

    customer = factory.SubFactory(CustomerFactory)
    balance = 0
