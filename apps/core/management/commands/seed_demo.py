"""
Seed demo/development data.

Usage:
    uv run python manage.py seed_demo

Creates (idempotent — safe to run multiple times):

  Seller & store
  - Superuser  rusydani.sh@gmail.com / admin1234!   → SellerProfile "Estalatree Store"
  - StorePage  slug="store"

  Product catalog  (SaaS tool — Estalatree Analytics)
  - Product "Estalatree Analytics" (RECURRING, PUBLIC)
    • Plan "Starter"  Rp 99.000 / month   — 1 seat   → LICENSE_KEY deliverable
    • Plan "Pro"      Rp 199.000 / month  — 3 seats  → LICENSE_KEY deliverable
    • Plan "Team"     Rp 499.000 / year   — 10 seats → LICENSE_KEY deliverable
  - Coupon  DEMO20  (20% off, max Rp 50.000, unlimited)
  - Coupon  NEWUSER (Rp 25.000 off, 1× per user — no plans restriction)

  Demo customers
  ┌──────────────────────────────────────────────────────────────────┐
  │ demo@example.com   / demo1234!   — active Starter sub, 2 devices │
  │ alice@example.com  / demo1234!   — active Pro sub, pending topup │
  │ bob@example.com    / demo1234!   — grace Starter sub (low balance)│
  │ carol@example.com  / demo1234!   — cancelled sub, refunded order  │
  └──────────────────────────────────────────────────────────────────┘

  Transactions per customer
  - TopUps (paid, credited to wallet)
  - Orders (paid) → Subscriptions → Licenses → Installations (devices)
  - One Order using coupon DEMO20
  - One cancelled Subscription
  - One refunded Order
  - Pending TopUp for alice (§2.1 demo)

  Console / system
  - Google SocialApp (from env, silently skipped if not set)
  - Setting TOPUP_BONUS_PERCENT = 5
"""
import os
import uuid
from datetime import timedelta

from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Customer, SellerProfile, User
from apps.billing.models import Coupon, Order, Subscription, TopUp
from apps.catalog.models import Plan, Product
from apps.core.models import Setting
from apps.licensing.models import Installation, License
from apps.provisioning.models import Deliverable, Grant
from apps.storefront.models import Block, StorePage
from apps.wallet.models import Wallet
from apps.wallet.services import credit, debit


class Command(BaseCommand):
    help = "Seed demo data (idempotent)"

    def handle(self, *args, **options):
        self._seed_superuser()
        self._seed_seller_profile()
        self._seed_store()
        self._seed_coupons()
        self._seed_settings()
        self._seed_customers()
        self._seed_google_app()
        self.stdout.write(self.style.SUCCESS("\nSeed complete!"))
        self.stdout.write("  demo@example.com   / demo1234!")
        self.stdout.write("  alice@example.com  / demo1234!")
        self.stdout.write("  bob@example.com    / demo1234!")
        self.stdout.write("  carol@example.com  / demo1234!")

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

    # ── Seller Profile ────────────────────────────────────────────────────────

    def _seed_seller_profile(self):
        su = User.objects.filter(email="rusydani.sh@gmail.com", is_superuser=True).first()
        if su is None:
            return

        # User may already have a SellerProfile from @seller_required auto-create
        existing = SellerProfile.objects.filter(user=su).first()
        if existing:
            if existing.slug != "store":
                # Rename slug to "store" only if no conflict
                if not SellerProfile.objects.filter(slug="store").exclude(pk=existing.pk).exists():
                    existing.slug = "store"
                    existing.name = "Estalatree Store"
                    existing.is_active = True
                    existing.is_approved = True
                    existing.save(update_fields=["slug", "name", "is_active", "is_approved", "updated_at"])
            self.stdout.write(f"  SellerProfile '{existing.slug}' OK")
            return

        profile, created = SellerProfile.objects.get_or_create(
            slug="store",
            defaults={
                "user": su,
                "name": "Estalatree Store",
                "is_active": True,
                "is_approved": True,
            },
        )
        if not created and profile.user is None:
            profile.user = su
            profile.save(update_fields=["user", "updated_at"])
        self.stdout.write(f"  SellerProfile 'store' {'created' if created else 'OK'}")

    def _get_seller(self):
        su = User.objects.filter(email="rusydani.sh@gmail.com", is_superuser=True).first()
        if su:
            return SellerProfile.objects.filter(user=su).first()
        return SellerProfile.objects.filter(slug="store").first()

    # ── StorePage + Product + Plans ───────────────────────────────────────────

    def _seed_store(self):
        seller = self._get_seller()

        store, s_created = StorePage.objects.get_or_create(
            slug="store",
            defaults={
                "title": "Estalatree Store",
                "description": "Alat analitik SaaS untuk tim digital.",
                "is_published": True,
            },
        )
        self.stdout.write(f"  StorePage 'store' {'created' if s_created else 'OK'}")

        product, p_created = Product.objects.get_or_create(
            slug="estalatree-analytics",
            defaults={
                "seller": seller,
                "name": "Estalatree Analytics",
                "type": Product.Type.RECURRING,
                "visibility": Product.Visibility.PUBLIC,
                "description": (
                    "Platform analitik real-time untuk bisnis digital. "
                    "Pantau traffic, konversi, dan revenue dalam satu dashboard."
                ),
            },
        )
        self.stdout.write(f"  Product 'Estalatree Analytics' {'created' if p_created else 'OK'}")

        plans_spec = [
            ("Starter", 99_000, Plan.Interval.MONTHLY, 1, 0),
            ("Pro",     199_000, Plan.Interval.MONTHLY, 3, 1),
            ("Team",    499_000, Plan.Interval.YEARLY,  10, 2),
        ]
        self.plans = {}
        for name, price, interval, seats, sort_order in plans_spec:
            plan, pl_created = Plan.objects.get_or_create(
                product=product,
                name=name,
                defaults={
                    "seller": seller,
                    "price": price,
                    "interval": interval,
                    "seat_limit": seats,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
            self.plans[name] = plan
            Deliverable.objects.get_or_create(
                plan=plan,
                type=Deliverable.Type.LICENSE_KEY,
                defaults={"config": {}},
            )
            self.stdout.write(
                f"    Plan '{name}' Rp{price:,}/{interval} {'created' if pl_created else 'OK'}"
            )

        # Attach all plans to the store page
        for plan in self.plans.values():
            if not Block.objects.filter(store_page=store, product=product).exists():
                Block.objects.create(
                    store_page=store,
                    type=Block.Type.PRODUCT,
                    position=1,
                    product=product,
                )
                break  # one block per product is enough

        # Legacy one-time product (kept from original seed)
        Product.objects.get_or_create(
            slug="pro-license",
            defaults={
                "seller": seller,
                "name": "Pro License",
                "type": Product.Type.ONE_TIME,
                "visibility": Product.Visibility.PUBLIC,
                "description": "Lifetime access to the Pro tier.",
            },
        )

    # ── Coupons ───────────────────────────────────────────────────────────────

    def _seed_coupons(self):
        seller = self._get_seller()
        Coupon.objects.get_or_create(
            code="DEMO20",
            defaults={
                "seller": seller,
                "discount_type": Coupon.DiscountType.PERCENT,
                "value": 20,
                "max_discount": 50_000,
                "usage_limit": 0,
                "is_active": True,
            },
        )
        Coupon.objects.get_or_create(
            code="NEWUSER",
            defaults={
                "seller": seller,
                "discount_type": Coupon.DiscountType.FIXED,
                "value": 25_000,
                "usage_limit": 1,
                "is_active": True,
            },
        )
        self.stdout.write("  Coupons DEMO20 + NEWUSER OK")

    # ── Settings ──────────────────────────────────────────────────────────────

    def _seed_settings(self):
        Setting.objects.get_or_create(
            key="TOPUP_BONUS_PERCENT",
            defaults={"value": "5", "description": "Bonus % credited on every top-up"},
        )
        self.stdout.write("  Setting TOPUP_BONUS_PERCENT = 5 OK")

    # ── Customers + full transaction histories ────────────────────────────────

    def _seed_customers(self):
        # Reload plans in case _seed_store was a no-op (already existed)
        try:
            starter = Plan.objects.get(product__slug="estalatree-analytics", name="Starter")
            pro = Plan.objects.get(product__slug="estalatree-analytics", name="Pro")
            team = Plan.objects.get(product__slug="estalatree-analytics", name="Team")
        except Plan.DoesNotExist:
            self.stdout.write(self.style.ERROR("  Plans missing — run seed_demo again"))
            return

        self._seed_demo(starter)
        self._seed_alice(pro)
        self._seed_bob(starter)
        self._seed_carol(starter)

    # ── demo@example.com: active Starter sub, 2 devices ──────────────────────

    def _seed_demo(self, starter):
        user, customer, wallet = self._get_or_create_customer("demo@example.com", "demo1234!")

        # Top-up Rp 300.000 (paid)
        self._credit_topup(wallet, customer, 300_000, "seed-demo-topup-1", "Topup via Duitku")
        # Bonus 5%
        self._credit_bonus(wallet, 15_000, "seed-demo-bonus-1", "Bonus 5% topup")

        # Order → Sub → License
        order, sub, lic = self._buy_plan(
            customer=customer,
            wallet=wallet,
            plan=starter,
            order_ref="seed-demo-ord-1",
            sub_days=30,
        )

        # 2nd month renewal (simulate auto-renew)
        order2, _, _ = self._buy_plan(
            customer=customer,
            wallet=wallet,
            plan=starter,
            order_ref="seed-demo-ord-2",
            sub_days=30,
            existing_license=lic,
            existing_sub=sub,
        )

        # Add 2 device installations
        Installation.objects.get_or_create(
            license=lic,
            fingerprint="demo-fp-macbook-001",
            defaults={"name": "MacBook Pro (Demo)", "status": Installation.Status.ACTIVE},
        )
        Installation.objects.get_or_create(
            license=lic,
            fingerprint="demo-fp-win-002",
            defaults={"name": "Windows PC (Kantor)", "status": Installation.Status.ACTIVE},
        )

        self.stdout.write("  demo@example.com — active Starter sub + 2 devices OK")

    # ── alice@example.com: active Pro sub + pending topup ────────────────────

    def _seed_alice(self, pro):
        user, customer, wallet = self._get_or_create_customer("alice@example.com", "demo1234!")

        # Top-up Rp 500.000 (paid) with coupon DEMO20 on purchase
        self._credit_topup(wallet, customer, 500_000, "seed-alice-topup-1", "Topup via Duitku")

        coupon = Coupon.objects.filter(code="DEMO20").first()
        order, sub, lic = self._buy_plan(
            customer=customer,
            wallet=wallet,
            plan=pro,
            order_ref="seed-alice-ord-1",
            sub_days=30,
            coupon=coupon,
        )

        # Add 1 device
        Installation.objects.get_or_create(
            license=lic,
            fingerprint="alice-fp-mac-001",
            defaults={"name": "MacBook Air (Alice)", "status": Installation.Status.ACTIVE},
        )

        # Pending top-up (not yet paid — §2.1 demo)
        TopUp.objects.get_or_create(
            gateway_ref="duitku-pending-alice-001",
            defaults={
                "customer": customer,
                "amount": 200_000,
                "bonus": 10_000,
                "gateway": TopUp.Gateway.DUITKU,
                "status": TopUp.Status.PENDING,
            },
        )

        self.stdout.write("  alice@example.com — active Pro sub + pending topup OK")

    # ── bob@example.com: grace period (balance too low for renewal) ───────────

    def _seed_bob(self, starter):
        user, customer, wallet = self._get_or_create_customer("bob@example.com", "demo1234!")

        # Top-up Rp 150.000 then spend it — leaves Rp 10.000 (insufficient for next Rp 99.000)
        self._credit_topup(wallet, customer, 150_000, "seed-bob-topup-1", "Topup via Duitku")

        order, sub, lic = self._buy_plan(
            customer=customer,
            wallet=wallet,
            plan=starter,
            order_ref="seed-bob-ord-1",
            sub_days=-3,  # already expired 3 days ago
        )

        # Force sub to GRACE status (balance insufficient)
        sub.status = Subscription.Status.GRACE
        sub.current_period_end = timezone.now() - timedelta(days=3)
        sub.save(update_fields=["status", "current_period_end", "updated_at"])

        # Force license to SUSPENDED
        lic.status = License.Status.SUSPENDED
        lic.save(update_fields=["status", "updated_at"])

        # Simulate grant suspended too
        if lic.grant:
            lic.grant.status = Grant.Status.SUSPENDED
            lic.grant.save(update_fields=["status", "updated_at"])

        self.stdout.write("  bob@example.com   — GRACE sub (balance Rp 51.000) OK")

    # ── carol@example.com: cancelled sub + refunded order ────────────────────

    def _seed_carol(self, starter):
        user, customer, wallet = self._get_or_create_customer("carol@example.com", "demo1234!")

        # Top-up Rp 200.000
        self._credit_topup(wallet, customer, 200_000, "seed-carol-topup-1", "Topup via Duitku")

        # Buy → then cancel sub + refund
        order, sub, lic = self._buy_plan(
            customer=customer,
            wallet=wallet,
            plan=starter,
            order_ref="seed-carol-ord-1",
            sub_days=30,
        )

        # Refund the order
        existing_refund = self._entry_exists(f"refund:{order.public_id}")
        if not existing_refund:
            wallet.refresh_from_db()
            credit(
                wallet,
                amount=order.amount,
                entry_type="refund",
                ref=f"refund:{order.public_id}",
                note="Demo refund — customer requested cancellation",
            )
            order.status = Order.Status.REFUNDED
            order.save(update_fields=["status", "updated_at"])

        # Cancel subscription
        sub.status = Subscription.Status.CANCELLED
        sub.auto_renew = False
        sub.save(update_fields=["status", "auto_renew", "updated_at"])

        # Revoke license
        lic.status = License.Status.REVOKED
        lic.save(update_fields=["status", "updated_at"])
        if lic.grant:
            lic.grant.status = Grant.Status.REVOKED
            lic.grant.save(update_fields=["status", "updated_at"])

        # Second order with NEWUSER coupon (shows coupon usage in seller voucher page)
        wallet.refresh_from_db()
        coupon = Coupon.objects.filter(code="NEWUSER").first()
        if wallet.balance >= starter.price and not self._entry_exists("seed-carol-ord-2-ledger"):
            self._buy_plan(
                customer=customer,
                wallet=wallet,
                plan=starter,
                order_ref="seed-carol-ord-2",
                sub_days=30,
                coupon=coupon,
            )

        self.stdout.write("  carol@example.com — CANCELLED sub + refund OK")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_or_create_customer(self, email, password):
        user, created = User.objects.get_or_create(
            email=email, defaults={"is_active": True}
        )
        if created:
            user.set_password(password)
            user.save()
        customer, _ = Customer.objects.get_or_create(user=user)
        # Ensure wallet exists (created by signal or get_or_create)
        wallet, _ = Wallet.objects.get_or_create(customer=customer)
        return user, customer, wallet

    def _credit_topup(self, wallet, customer, amount, ref, note):
        """Credit wallet and create a paid TopUp record."""
        topup, t_created = TopUp.objects.get_or_create(
            gateway_ref=ref,
            defaults={
                "customer": customer,
                "amount": amount,
                "bonus": 0,
                "gateway": TopUp.Gateway.DUITKU,
                "status": TopUp.Status.PAID,
            },
        )
        if t_created:
            entry = credit(
                wallet,
                amount=amount,
                entry_type="topup",
                ref=f"topup:{topup.public_id}",
                note=note,
            )
            topup.ledger_entry = entry
            topup.save(update_fields=["ledger_entry", "updated_at"])

    def _credit_bonus(self, wallet, amount, ref, note):
        if not self._entry_exists(ref):
            credit(wallet, amount=amount, entry_type="bonus", ref=ref, note=note)

    def _entry_exists(self, ref):
        from apps.wallet.models import LedgerEntry
        return LedgerEntry.objects.filter(ref=ref).exists()

    def _buy_plan(
        self, *, customer, wallet, plan, order_ref, sub_days,
        coupon=None, existing_license=None, existing_sub=None,
    ):
        """
        Create a paid Order → Subscription → License (idempotent).

        Returns (order, subscription, license).
        """
        # --- Order ---
        order = Order.objects.filter(idempotency_key=order_ref).first()
        if order is None:
            discount = 0
            if coupon:
                valid, _ = coupon.is_valid_for(plan)
                if valid:
                    discount = coupon.compute_discount(plan.price)

            effective_amount = max(0, plan.price - discount)
            wallet.refresh_from_db()

            order = Order.objects.create(
                customer=customer,
                plan=plan,
                amount=effective_amount,
                status=Order.Status.PAID,
                idempotency_key=order_ref,
                coupon=coupon if discount > 0 else None,
                discount=discount,
            )

            # Debit wallet
            ledger_ref = f"order:{order.public_id}"
            if not self._entry_exists(ledger_ref) and effective_amount > 0:
                wallet.refresh_from_db()
                entry = debit(
                    wallet,
                    amount=effective_amount,
                    entry_type="purchase",
                    ref=ledger_ref,
                    note=f"Order {order.public_id} — {plan.name}",
                )
                order.ledger_entry = entry
                order.save(update_fields=["ledger_entry", "updated_at"])

            # Increment coupon counter
            if coupon and discount > 0:
                from django.db.models import F
                Coupon.objects.filter(pk=coupon.pk).update(used_count=F("used_count") + 1)
                coupon.refresh_from_db()

        # --- Subscription ---
        if existing_sub:
            sub = existing_sub
            # Extend period
            now = timezone.now()
            if plan.interval == Plan.Interval.YEARLY:
                sub.current_period_end = now + timedelta(days=365)
            else:
                sub.current_period_end = now + timedelta(days=sub_days if sub_days > 0 else 30)
            sub.save(update_fields=["current_period_end", "updated_at"])
        else:
            sub = Subscription.objects.filter(
                customer=customer,
                plan=plan,
            ).exclude(
                status__in=[Subscription.Status.CANCELLED]
            ).first()

            if sub is None:
                now = timezone.now()
                if sub_days > 0:
                    period_end = now + timedelta(days=sub_days)
                else:
                    period_end = now + timedelta(days=sub_days)  # will be negative → past

                sub = Subscription.objects.create(
                    customer=customer,
                    plan=plan,
                    status=Subscription.Status.ACTIVE,
                    current_period_end=period_end,
                    auto_renew=True,
                )
                order.subscription = sub
                order.save(update_fields=["subscription", "updated_at"])

        # --- Grant + License ---
        if existing_license:
            lic = existing_license
        else:
            lic = License.objects.filter(customer=customer, plan=plan).exclude(
                status=License.Status.REVOKED
            ).first()

            if lic is None:
                # Create Grant
                deliverable = plan.deliverables.filter(type=Deliverable.Type.LICENSE_KEY).first()
                if deliverable:
                    grant = Grant.objects.create(
                        customer=customer,
                        order=order,
                        subscription=sub,
                        deliverable=deliverable,
                        type=Deliverable.Type.LICENSE_KEY,
                        status=Grant.Status.ACTIVE,
                        payload={},
                    )
                    # Create License
                    lic = License.objects.create(
                        customer=customer,
                        plan=plan,
                        subscription=sub,
                        grant=grant,
                        status=License.Status.ACTIVE,
                        seat_limit=plan.seat_limit,
                    )
                    grant.payload = {"license_id": lic.pk}
                    grant.save(update_fields=["payload", "updated_at"])
                else:
                    lic = None

        return order, sub, lic

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
                app.client_id = client_id
                app.secret = client_secret
                app.save(update_fields=["client_id", "secret"])

            app.sites.add(site)
            verb = "Created" if created else "Updated"
            self.stdout.write(f"  {verb} Google SocialApp")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(f"  Google SocialApp error: {exc}"))
