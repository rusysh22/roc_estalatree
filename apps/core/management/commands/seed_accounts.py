"""Seed 4 dummy accounts, one per role, for local testing.

Usage:
    python manage.py seed_accounts

Idempotent — safe to rerun. All accounts share the password below.

  Role        Email                    Access surface
  ─────────── ──────────────────────── ───────────────────────────────
  Superadmin  superadmin@demo.test     /admin/  + /console/  (full RBAC)
  Operator    operator@demo.test       /console/  (Operator group)
  Seller      seller@demo.test         /seller/   (approved SellerProfile)
  Customer    customer@demo.test       /dashboard/  (wallet pre-funded)
"""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Customer, SellerProfile, User

PASSWORD = "demo1234!"


class Command(BaseCommand):
    help = "Create 4 dummy accounts (superadmin / operator / seller / customer)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding dummy accounts…"))

        self._superadmin()
        self._operator()
        self._seller()
        self._customer()

        self.stdout.write(self.style.SUCCESS("\nDone. Password for all accounts: " + PASSWORD))
        self.stdout.write("")
        self.stdout.write("  Superadmin  superadmin@demo.test   ->  /admin/  &  /console/")
        self.stdout.write("  Operator    operator@demo.test     ->  /console/")
        self.stdout.write("  Seller      seller@demo.test       ->  /seller/")
        self.stdout.write("  Customer    customer@demo.test     ->  /dashboard/")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _user(self, email, **flags):
        user, created = User.objects.get_or_create(email=email)
        user.set_password(PASSWORD)
        user.is_active = True
        for k, v in flags.items():
            setattr(user, k, v)
        user.save()
        self._verify_email(user)
        self.stdout.write(f"  {'created' if created else 'updated'}  {email}")
        return user

    def _verify_email(self, user):
        """Mark the email verified so allauth flows / checkout don't nag."""
        try:
            from allauth.account.models import EmailAddress
            EmailAddress.objects.update_or_create(
                user=user, email=user.email,
                defaults={"primary": True, "verified": True},
            )
        except Exception:
            pass

    # ── roles ────────────────────────────────────────────────────────────────

    def _superadmin(self):
        self._user("superadmin@demo.test", is_staff=True, is_superuser=True)

    def _operator(self):
        user = self._user("operator@demo.test", is_staff=True, is_superuser=False)
        group, _ = Group.objects.get_or_create(name="Operator")
        user.groups.add(group)

    def _seller(self):
        user = self._user("seller@demo.test")
        SellerProfile.objects.update_or_create(
            user=user,
            defaults={
                "name": "Demo Seller Store",
                "slug": "demo-seller",
                "is_active": True,
                "is_approved": True,
                "onboarding_completed": True,
                "onboarding_step": SellerProfile.OnboardingStep.PUBLISH,
                "bio": "Dummy seller account for local testing.",
                "wa_number": "628111111111",
                "payout_bank_name": "BCA",
                "payout_account_number": "1234567890",
                "payout_account_name": "Demo Seller",
            },
        )

    def _customer(self):
        user = self._user("customer@demo.test")
        customer, _ = Customer.objects.get_or_create(
            user=user, defaults={"wa_number": "628222222222"}
        )
        # Wallet is auto-created by a post_save signal; top it up for testing.
        from apps.wallet.models import LedgerEntry
        from apps.wallet.services import credit
        customer.wallet.refresh_from_db()
        if customer.wallet.balance < 500_000:
            credit(
                wallet=customer.wallet,
                amount=500_000 - customer.wallet.balance,
                entry_type=LedgerEntry.Type.ADJUSTMENT,
                ref=f"seed_accounts:{customer.pk}",
                note="Seed: starting balance for dummy customer",
            )
