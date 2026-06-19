"""
Seed demo/development data.

Usage:
    uv run python manage.py seed_demo

Creates (idempotent — safe to run multiple times):
  - Superuser  rusydani.sh@gmail.com / admin1234!
  - Demo customer  demo@example.com / demo1234!
  - StorePage  slug="store"
  - Product "Pro License" (ONE_TIME, PUBLIC) + Plan "Pro" (Rp 99,000)
  - Deliverable (LICENSE_KEY) attached to the plan
  - Google SocialApp (reads GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET from env)
"""
import os

from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.catalog.models import Plan, Product
from apps.provisioning.models import Deliverable
from apps.storefront.models import Block, StorePage


class Command(BaseCommand):
    help = "Seed demo data (idempotent)"

    def handle(self, *args, **options):
        self._seed_superuser()
        self._seed_demo_customer()
        self._seed_store()
        self._seed_google_app()
        self.stdout.write(self.style.SUCCESS("Seed complete."))

    # ── Superuser ─────────────────────────────────────────────────────────────

    def _seed_superuser(self):
        email = "rusydani.sh@gmail.com"
        if not User.objects.filter(email=email).exists():
            User.objects.create_superuser(email=email, password="admin1234!")
            self.stdout.write(f"  Created superuser {email}")
        else:
            su = User.objects.get(email=email)
            if not su.is_superuser or not su.is_staff:
                su.is_superuser = True
                su.is_staff = True
                su.save(update_fields=["is_superuser", "is_staff"])
            self.stdout.write(f"  Superuser {email} OK")

    # ── Demo customer ─────────────────────────────────────────────────────────

    def _seed_demo_customer(self):
        from apps.accounts.models import Customer

        email = "demo@example.com"
        user, created = User.objects.get_or_create(
            email=email,
            defaults={"is_active": True},
        )
        if created:
            user.set_password("demo1234!")
            user.save()
            self.stdout.write(f"  Created demo user {email}")
        Customer.objects.get_or_create(user=user)
        self.stdout.write(f"  Demo customer {email} OK")

    # ── StorePage + Product + Plan ────────────────────────────────────────────

    def _seed_store(self):
        store, created = StorePage.objects.get_or_create(
            slug="store",
            defaults={
                "title": "Estalatree Store",
                "description": "Digital products and software licenses.",
                "is_published": True,
            },
        )
        if created:
            self.stdout.write("  Created StorePage 'store'")
        else:
            self.stdout.write("  StorePage 'store' OK")

        product, p_created = Product.objects.get_or_create(
            slug="pro-license",
            defaults={
                "name": "Pro License",
                "type": Product.Type.ONE_TIME,
                "visibility": Product.Visibility.PUBLIC,
                "description": "Lifetime access to the Pro tier.",
            },
        )
        if p_created:
            self.stdout.write("  Created Product 'Pro License'")

        plan, pl_created = Plan.objects.get_or_create(
            product=product,
            name="Pro",
            defaults={
                "price": 99_000,
                "interval": Plan.Interval.NONE,
                "is_active": True,
            },
        )
        if pl_created:
            self.stdout.write("  Created Plan 'Pro' (Rp 99,000)")

        Deliverable.objects.get_or_create(
            plan=plan,
            type=Deliverable.Type.LICENSE_KEY,
            defaults={"config": {}},
        )

        # Attach product block to store page if not already there
        if not Block.objects.filter(store_page=store, product=product).exists():
            Block.objects.create(
                store_page=store,
                type=Block.Type.PRODUCT,
                position=1,
                product=product,
            )
            self.stdout.write("  Attached product block to StorePage")

    # ── Google SocialApp ──────────────────────────────────────────────────────

    def _seed_google_app(self):
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

        if not client_id:
            self.stdout.write(
                self.style.WARNING(
                    "  GOOGLE_CLIENT_ID not set — skipping Google SocialApp."
                )
            )
            return

        try:
            from allauth.socialaccount.models import SocialApp

            site = Site.objects.get_current()
            app, created = SocialApp.objects.get_or_create(
                provider="google",
                defaults={
                    "name": "Google",
                    "client_id": client_id,
                    "secret": client_secret,
                },
            )
            if not created:
                # Update credentials in case they changed
                app.client_id = client_id
                app.secret = client_secret
                app.save(update_fields=["client_id", "secret"])

            app.sites.add(site)
            verb = "Created" if created else "Updated"
            self.stdout.write(f"  {verb} Google SocialApp")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(f"  Google SocialApp error: {exc}"))
