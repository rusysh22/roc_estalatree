"""
Seed demo/development data — covers Phases 1–16.

Usage:
    uv run python manage.py seed_demo

Idempotent — safe to run multiple times.

Accounts
  superuser   rusydani.sh@gmail.com / admin1234!
  customers   demo@example.com / alice@example.com / bob@example.com / carol@example.com
              password: demo1234!

Seller
  SellerProfile  "Dani Digital Store"  slug=dani
  StorePage      published, themed, linked to seller
  SellerProfile  payout bank + GA pixel stub

Products (all linked to seller)
  1. Estalatree Analytics       RECURRING  — 3 plans (Starter/Pro/Team) + LICENSE_KEY
  2. Ultimate Design Pack       ONE_TIME   — 1 plan, sale_price, stock
  3. Name Your Price Template   ONE_TIME   — PWYW plan, min Rp 15.000
  4. Copywriting Masterclass    ONE_TIME   — COURSE deliverable, modules + lessons
  5. WhatsApp Lead Widget       CONTACT    — wa_number

Extras
  Coupons: DEMO20, NEWUSER, LAUNCH50
  Affiliate link: DEMOREF (10%)
  Course: 2 modules × 3 lessons
  Checkout questions on Design Pack
  ProductReviews on Analytics & Design Pack
  PageEvents (funnel simulation)
  SellerEarnings from all paid orders
"""
import os
import uuid
from datetime import timedelta

from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Customer, SellerProfile, User
from apps.billing.models import (
    AffiliateLink, Coupon, Order, SellerEarning, Subscription, TopUp,
)
from apps.catalog.models import (
    CourseLesson, CourseModule, Plan, Product, ProductQuestion, ProductReview,
)
from apps.core.models import Setting
from apps.licensing.models import Installation, License
from apps.provisioning.models import Deliverable, Grant
from apps.storefront.models import Block, PageEvent, StorePage
from apps.wallet.models import Wallet
from apps.wallet.services import credit, debit


class Command(BaseCommand):
    help = "Seed demo data (idempotent — safe to rerun)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding demo data…"))
        self._seed_superuser()
        seller = self._seed_seller_profile()
        store = self._seed_store(seller)
        products = self._seed_products(seller, store)
        self._seed_coupons(seller, products)
        self._seed_settings()
        customers = self._seed_customers(products, seller)
        self._seed_affiliate(seller, products)
        self._seed_page_events(products, customers)
        self._seed_google_app()

        self.stdout.write(self.style.SUCCESS("\nSeed complete!\n"))
        self.stdout.write("  Login (seller/admin):  rusydani.sh@gmail.com  / admin1234!")
        self.stdout.write("  Customers (pw: demo1234!):")
        self.stdout.write("    demo@example.com   active Starter sub + 2 devices")
        self.stdout.write("    alice@example.com  active Pro sub + coupon DEMO20")
        self.stdout.write("    bob@example.com    grace period (low balance)")
        self.stdout.write("    carol@example.com  cancelled + refunded")

    # ── Superuser ─────────────────────────────────────────────────────────────

    def _seed_superuser(self):
        email = "rusydani.sh@gmail.com"
        user, created = User.objects.get_or_create(email=email)
        if created:
            user.set_password("admin1234!")
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.save()
        verb = "created" if created else "OK"
        self.stdout.write(f"  Superuser {email} {verb}")
        return user

    # ── Seller Profile ────────────────────────────────────────────────────────

    def _seed_seller_profile(self):
        su = User.objects.get(email="rusydani.sh@gmail.com")
        seller, created = SellerProfile.objects.get_or_create(
            user=su,
            defaults={
                "name": "Dani Digital Store",
                "slug": "dani",
                "is_active": True,
                "is_approved": True,
                "bio": "Template, tools, dan kursus digital untuk kreator Indonesia.",
                "commission_rate": 0,
                "plan": SellerProfile.Plan.PRO,
                "payout_bank_name": "BCA",
                "payout_account_number": "1234567890",
                "payout_account_name": "Rusydani Shubkhi",
                "ga_tracking_id": "G-DEMO1234XX",
            },
        )
        if not created:
            # Ensure slug is set
            if not seller.slug:
                seller.slug = "dani"
                seller.save(update_fields=["slug", "updated_at"])
        self.stdout.write(f"  SellerProfile '{seller.slug}' {'created' if created else 'OK'}")
        return seller

    # ── StorePage ─────────────────────────────────────────────────────────────

    def _seed_store(self, seller):
        store, created = StorePage.objects.get_or_create(
            slug="dani",
            defaults={
                "title": "Dani Digital Store",
                "description": "Template premium, tools SaaS, dan kursus copywriting terbaik untuk bisnis digital kamu.",
                "avatar_url": "https://ui-avatars.com/api/?name=Dani&background=4f46e5&color=fff&size=128",
                "is_published": True,
                "seller": seller,
                "theme": {
                    "primary_color": "#4f46e5",
                    "background_color": "#f5f3ff",
                    "layout": "grid",
                    "banner_url": "",
                },
            },
        )
        if not created and store.seller_id != seller.pk:
            store.seller = seller
            store.save(update_fields=["seller", "updated_at"])
        self.stdout.write(f"  StorePage 'dani' {'created' if created else 'OK'}")
        return store

    # ── Products ──────────────────────────────────────────────────────────────

    def _seed_products(self, seller, store):
        products = {}

        # 1. RECURRING — Analytics SaaS
        analytics, _ = Product.objects.get_or_create(
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
                "cover_image_url": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=640&q=80",
            },
        )
        products["analytics"] = analytics
        starter = self._ensure_plan(analytics, seller, "Starter", 99_000, Plan.Interval.MONTHLY, sort=0, seats=1)
        pro_plan = self._ensure_plan(analytics, seller, "Pro", 199_000, Plan.Interval.MONTHLY, sort=1, seats=3)
        team_plan = self._ensure_plan(analytics, seller, "Team", 499_000, Plan.Interval.YEARLY, sort=2, seats=10)
        for p in [starter, pro_plan, team_plan]:
            Deliverable.objects.get_or_create(plan=p, type=Deliverable.Type.LICENSE_KEY, defaults={"config": {}})
        products["starter"] = starter
        products["pro_plan"] = pro_plan
        products["team_plan"] = team_plan
        self.stdout.write("  Product: Estalatree Analytics (RECURRING) OK")

        # 2. ONE_TIME — Design Pack (sale price + stock + questions)
        design, _ = Product.objects.get_or_create(
            slug="ultimate-design-pack",
            defaults={
                "seller": seller,
                "name": "Ultimate Design Pack",
                "type": Product.Type.ONE_TIME,
                "visibility": Product.Visibility.PUBLIC,
                "description": (
                    "500+ template Canva & Figma siap pakai untuk konten media sosial, pitch deck, dan landing page."
                ),
                "cover_image_url": "https://images.unsplash.com/photo-1561070791-2526d30994b5?w=640&q=80",
                "purchase_button_label": "Dapatkan Sekarang",
            },
        )
        products["design"] = design
        design_plan = self._ensure_plan(
            design, seller, "Lifetime Access", 149_000, Plan.Interval.NONE, sort=0,
            extra={"sale_price": 99_000, "stock_quantity": 50},
        )
        Deliverable.objects.get_or_create(plan=design_plan, type=Deliverable.Type.DOWNLOAD, defaults={"config": {"url": "https://example.com/demo-pack.zip"}})
        products["design_plan"] = design_plan
        # Checkout questions
        ProductQuestion.objects.get_or_create(
            product=design, label="Platform yang kamu gunakan?",
            defaults={"sort_order": 0, "required": True},
        )
        ProductQuestion.objects.get_or_create(
            product=design, label="Link portofolio (opsional)",
            defaults={"sort_order": 1, "required": False},
        )
        self.stdout.write("  Product: Ultimate Design Pack (ONE_TIME, sale_price, stock) OK")

        # 3. ONE_TIME — PWYW Template
        pwyw_prod, _ = Product.objects.get_or_create(
            slug="name-your-price-template",
            defaults={
                "seller": seller,
                "name": "Social Media Caption Template",
                "type": Product.Type.ONE_TIME,
                "visibility": Product.Visibility.PUBLIC,
                "description": "100 template caption Instagram + TikTok. Bayar sesuai kemampuan kamu!",
                "cover_image_url": "https://images.unsplash.com/photo-1611926653458-09294b3142bf?w=640&q=80",
                "purchase_button_label": "Pilih Hargamu",
            },
        )
        products["pwyw"] = pwyw_prod
        pwyw_plan = self._ensure_plan(
            pwyw_prod, seller, "Pay What You Want", 0, Plan.Interval.NONE, sort=0,
            extra={"pwyw": True, "min_price": 15_000},
        )
        Deliverable.objects.get_or_create(plan=pwyw_plan, type=Deliverable.Type.DOWNLOAD, defaults={"config": {"url": "https://example.com/caption-templates.pdf"}})
        products["pwyw_plan"] = pwyw_plan
        self.stdout.write("  Product: Caption Template (PWYW, min Rp15k) OK")

        # 4. ONE_TIME — Course product
        course_prod, _ = Product.objects.get_or_create(
            slug="copywriting-masterclass",
            defaults={
                "seller": seller,
                "name": "Copywriting Masterclass",
                "type": Product.Type.ONE_TIME,
                "visibility": Product.Visibility.PUBLIC,
                "description": (
                    "Kuasai seni menulis copy yang menjual. "
                    "Dari hook yang kuat hingga CTA yang konversi — 6 modul video + teks."
                ),
                "cover_image_url": "https://images.unsplash.com/photo-1455390582262-044cdead277a?w=640&q=80",
                "purchase_button_label": "Mulai Belajar",
            },
        )
        products["course"] = course_prod
        course_plan = self._ensure_plan(course_prod, seller, "Full Access", 299_000, Plan.Interval.NONE, sort=0)
        Deliverable.objects.get_or_create(plan=course_plan, type=Deliverable.Type.COURSE, defaults={"config": {}})
        products["course_plan"] = course_plan
        self._seed_course_content(course_prod)
        self.stdout.write("  Product: Copywriting Masterclass (COURSE) OK")

        # 5. CONTACT — WA Lead
        contact_prod, _ = Product.objects.get_or_create(
            slug="konsultasi-gratis",
            defaults={
                "seller": seller,
                "name": "Konsultasi Gratis 30 Menit",
                "type": Product.Type.CONTACT,
                "visibility": Product.Visibility.PUBLIC,
                "description": "Book sesi konsultasi 1-on-1 gratis 30 menit tentang strategi digital marketing bisnis kamu.",
                "wa_number": "6281234567890",
            },
        )
        products["contact"] = contact_prod
        self.stdout.write("  Product: Konsultasi Gratis (CONTACT) OK")

        # Store blocks
        pos = 1
        for key, prod in [("analytics", analytics), ("design", design), ("pwyw", pwyw_prod), ("course", course_prod), ("contact", contact_prod)]:
            if not Block.objects.filter(store_page=store, product=prod).exists():
                Block.objects.create(store_page=store, type=Block.Type.PRODUCT, position=pos, product=prod)
                pos += 1

        # Heading block
        if not Block.objects.filter(store_page=store, type=Block.Type.HEADING).exists():
            Block.objects.create(
                store_page=store, type=Block.Type.HEADING, position=0,
                config={"text": "🔥 Produk Digital Terlaris"},
            )

        return products

    def _ensure_plan(self, product, seller, name, price, interval, sort=0, seats=1, extra=None):
        plan, _ = Plan.objects.get_or_create(
            product=product, name=name,
            defaults={
                "seller": seller,
                "price": price,
                "interval": interval,
                "seat_limit": seats,
                "sort_order": sort,
                "is_active": True,
                **(extra or {}),
            },
        )
        return plan

    def _seed_course_content(self, product):
        mod1, _ = CourseModule.objects.get_or_create(
            product=product, title="Modul 1: Dasar Copywriting",
            defaults={"sort_order": 0},
        )
        mod2, _ = CourseModule.objects.get_or_create(
            product=product, title="Modul 2: Framework AIDA & PAS",
            defaults={"sort_order": 1},
        )

        lessons_m1 = [
            ("Apa Itu Copywriting?", "text", "Copywriting adalah seni menulis teks yang mendorong pembaca untuk mengambil tindakan.", 0, True),
            ("Mengenal Target Audience", "text", "Sebelum menulis, kamu harus tahu siapa yang kamu ajak bicara.", 1, False),
            ("Video: Hook yang Kuat", "video", "https://www.youtube.com/embed/dQw4w9WgXcQ", 2, False),
        ]
        lessons_m2 = [
            ("Framework AIDA", "text", "Attention, Interest, Desire, Action — formula klasik yang selalu bekerja.", 0, True),
            ("Framework PAS", "text", "Problem, Agitate, Solution — cocok untuk konten yang problem-aware.", 1, False),
            ("Latihan: Tulis Copy Pertamamu", "file", "https://example.com/latihan-copy.pdf", 2, False),
        ]
        for mod, lessons in [(mod1, lessons_m1), (mod2, lessons_m2)]:
            for title, ltype, content, sort, is_preview in lessons:
                CourseLesson.objects.get_or_create(
                    module=mod, title=title,
                    defaults={
                        "lesson_type": ltype,
                        "content": content if ltype in ("text", "video") else "",
                        "file_url": content if ltype == "file" else "",
                        "sort_order": sort,
                        "is_preview": is_preview,
                    },
                )
        self.stdout.write("    Course: 2 modules × 3 lessons seeded")

    # ── Coupons ───────────────────────────────────────────────────────────────

    def _seed_coupons(self, seller, products):
        Coupon.objects.get_or_create(
            code="DEMO20",
            defaults={
                "seller": seller, "discount_type": Coupon.DiscountType.PERCENT,
                "value": 20, "max_discount": 50_000, "usage_limit": 0, "is_active": True,
            },
        )
        Coupon.objects.get_or_create(
            code="NEWUSER",
            defaults={
                "seller": seller, "discount_type": Coupon.DiscountType.FIXED,
                "value": 25_000, "usage_limit": 1, "is_active": True,
            },
        )
        Coupon.objects.get_or_create(
            code="LAUNCH50",
            defaults={
                "seller": seller, "discount_type": Coupon.DiscountType.PERCENT,
                "value": 50, "max_discount": 75_000, "usage_limit": 100, "is_active": True,
            },
        )
        self.stdout.write("  Coupons: DEMO20 + NEWUSER + LAUNCH50 OK")

    # ── Settings ──────────────────────────────────────────────────────────────

    def _seed_settings(self):
        defaults = {
            "TOPUP_BONUS_PERCENT": ("5", "Bonus % credited on every top-up"),
            "MIN_TOPUP": ("10000", "Minimum top-up amount IDR"),
            "MAX_TOPUP": ("50000000", "Maximum top-up amount IDR"),
            "SUPPORT_WA_NUMBER": ("6281234567890", "Default support WhatsApp number"),
        }
        for key, (val, desc) in defaults.items():
            Setting.objects.get_or_create(key=key, defaults={"value": val, "description": desc})
        self.stdout.write("  Settings OK")

    # ── Customers ─────────────────────────────────────────────────────────────

    def _seed_customers(self, products, seller):
        starter = products["starter"]
        pro_plan = products["pro_plan"]
        design_plan = products["design_plan"]
        course_plan = products["course_plan"]
        pwyw_plan = products["pwyw_plan"]

        customers = {}

        # demo — active Starter + course + review
        user_d, cust_d, wallet_d = self._ensure_customer("demo@example.com")
        self._credit_topup(wallet_d, cust_d, 500_000, "seed-demo-topup-1")
        self._credit_topup(wallet_d, cust_d, 200_000, "seed-demo-topup-2")
        ord_d, sub_d, lic_d = self._buy_plan(cust_d, wallet_d, starter, "seed-demo-ord-1", 28)
        self._buy_plan(cust_d, wallet_d, starter, "seed-demo-ord-2", 30, existing_sub=sub_d, existing_lic=lic_d)
        ord_course, _, _ = self._buy_plan(cust_d, wallet_d, course_plan, "seed-demo-course-1", 0)
        ord_design, _, _ = self._buy_plan(cust_d, wallet_d, design_plan, "seed-demo-design-1", 0)
        Installation.objects.get_or_create(license=lic_d, fingerprint="demo-fp-mac-001",
            defaults={"name": "MacBook Pro (Demo)", "status": Installation.Status.ACTIVE})
        Installation.objects.get_or_create(license=lic_d, fingerprint="demo-fp-win-002",
            defaults={"name": "Windows PC (Kantor)", "status": Installation.Status.ACTIVE})
        self._ensure_review(ord_d, products["analytics"], 5, "Sangat membantu! Dashboard-nya clean dan data akurat real-time.")
        self._ensure_review(ord_design, products["design"], 5, "Worth it banget! 500+ template langsung bisa dipakai.")
        customers["demo"] = cust_d
        self._ensure_seller_earnings(seller, ord_d, ord_course, ord_design)
        self.stdout.write("  demo@example.com — Starter sub + course + design OK")

        # alice — Pro + coupon DEMO20 + pending topup
        user_a, cust_a, wallet_a = self._ensure_customer("alice@example.com")
        self._credit_topup(wallet_a, cust_a, 500_000, "seed-alice-topup-1")
        coupon20 = Coupon.objects.get(code="DEMO20")
        ord_a, sub_a, lic_a = self._buy_plan(cust_a, wallet_a, pro_plan, "seed-alice-ord-1", 30, coupon=coupon20)
        ord_a_pwyw, _, _ = self._buy_plan(cust_a, wallet_a, pwyw_plan, "seed-alice-pwyw-1", 0, pwyw_price=25_000)
        Installation.objects.get_or_create(license=lic_a, fingerprint="alice-fp-mac-001",
            defaults={"name": "MacBook Air (Alice)", "status": Installation.Status.ACTIVE})
        TopUp.objects.get_or_create(gateway_ref="duitku-pending-alice-001",
            defaults={"customer": cust_a, "amount": 200_000, "bonus": 10_000,
                      "gateway": TopUp.Gateway.DUITKU, "status": TopUp.Status.PENDING})
        self._ensure_review(ord_a, products["analytics"], 4, "Pro plan worth it untuk tim kecil. Fitur multi-seat sangat berguna.")
        customers["alice"] = cust_a
        self._ensure_seller_earnings(seller, ord_a, ord_a_pwyw)
        self.stdout.write("  alice@example.com — Pro sub + coupon + PWYW OK")

        # bob — grace period
        user_b, cust_b, wallet_b = self._ensure_customer("bob@example.com")
        self._credit_topup(wallet_b, cust_b, 150_000, "seed-bob-topup-1")
        ord_b, sub_b, lic_b = self._buy_plan(cust_b, wallet_b, starter, "seed-bob-ord-1", -3)
        sub_b.status = Subscription.Status.GRACE
        sub_b.current_period_end = timezone.now() - timedelta(days=3)
        sub_b.save(update_fields=["status", "current_period_end", "updated_at"])
        lic_b.status = License.Status.SUSPENDED
        lic_b.save(update_fields=["status", "updated_at"])
        if lic_b.grant:
            lic_b.grant.status = Grant.Status.SUSPENDED
            lic_b.grant.save(update_fields=["status", "updated_at"])
        customers["bob"] = cust_b
        self._ensure_seller_earnings(seller, ord_b)
        self.stdout.write("  bob@example.com — GRACE sub (low balance) OK")

        # carol — cancelled + refunded + NEWUSER coupon
        user_c, cust_c, wallet_c = self._ensure_customer("carol@example.com")
        self._credit_topup(wallet_c, cust_c, 300_000, "seed-carol-topup-1")
        ord_c, sub_c, lic_c = self._buy_plan(cust_c, wallet_c, starter, "seed-carol-ord-1", 30)
        # Refund
        if not self._entry_exists(f"refund:{ord_c.public_id}"):
            wallet_c.refresh_from_db()
            credit(wallet_c, amount=ord_c.amount, entry_type="refund",
                   ref=f"refund:{ord_c.public_id}", note="Demo refund — customer request")
            ord_c.status = Order.Status.REFUNDED
            ord_c.save(update_fields=["status", "updated_at"])
        sub_c.status = Subscription.Status.CANCELLED
        sub_c.auto_renew = False
        sub_c.save(update_fields=["status", "auto_renew", "updated_at"])
        lic_c.status = License.Status.REVOKED
        lic_c.save(update_fields=["status", "updated_at"])
        if lic_c.grant:
            lic_c.grant.status = Grant.Status.REVOKED
            lic_c.grant.save(update_fields=["status", "updated_at"])
        # Second purchase with NEWUSER coupon
        coupon_new = Coupon.objects.get(code="NEWUSER")
        wallet_c.refresh_from_db()
        if wallet_c.balance >= (starter.price - 25_000):
            self._buy_plan(cust_c, wallet_c, design_plan, "seed-carol-design-1", 0, coupon=coupon_new)
        customers["carol"] = cust_c
        self.stdout.write("  carol@example.com — CANCELLED + refund + NEWUSER coupon OK")

        return customers

    # ── Affiliate ─────────────────────────────────────────────────────────────

    def _seed_affiliate(self, seller, products):
        AffiliateLink.objects.get_or_create(
            code="DEMOREF",
            defaults={
                "seller": seller,
                "commission_rate": 10,
                "label": "Demo referral link",
                "is_active": True,
                "clicks": 42,
            },
        )
        AffiliateLink.objects.get_or_create(
            code="PARTNER1",
            defaults={
                "seller": seller,
                "product": products["design"],
                "commission_rate": 15,
                "label": "Design Pack partner",
                "is_active": True,
                "clicks": 18,
            },
        )
        self.stdout.write("  Affiliate links: DEMOREF + PARTNER1 OK")

    # ── PageEvents (analytics funnel simulation) ──────────────────────────────

    def _seed_page_events(self, products, customers):
        analytics = products["analytics"]
        design = products["design"]
        starter = products["starter"]
        design_plan = products["design_plan"]

        events_data = [
            # (event, product, plan, days_ago, count)
            ("page_view",       None,     None,         0, 15),
            ("page_view",       None,     None,         1, 12),
            ("page_view",       None,     None,         2, 18),
            ("page_view",       None,     None,         3, 9),
            ("page_view",       None,     None,         4, 22),
            ("page_view",       None,     None,         5, 7),
            ("page_view",       None,     None,         6, 14),
            ("product_view",    analytics, starter,     0, 8),
            ("product_view",    analytics, starter,     1, 6),
            ("product_view",    design,   design_plan,  0, 5),
            ("product_view",    design,   design_plan,  2, 9),
            ("checkout_start",  analytics, starter,     0, 3),
            ("checkout_start",  design,   design_plan,  0, 2),
            ("order_paid",      analytics, starter,     0, 2),
            ("order_paid",      design,   design_plan,  1, 1),
        ]

        created = 0
        for event, product, plan, days_ago, count in events_data:
            ts = timezone.now() - timedelta(days=days_ago, hours=3)
            for _ in range(count):
                if PageEvent.objects.filter(event=event, product=product, plan=plan,
                                            created_at__date=ts.date()).count() < count:
                    PageEvent.objects.create(
                        event=event, product=product, plan=plan,
                        session_key=uuid.uuid4().hex[:16],
                        created_at=ts,
                    )
                    created += 1
        self.stdout.write(f"  PageEvents: {created} analytics events seeded")

    # ── SellerEarnings ────────────────────────────────────────────────────────

    def _ensure_seller_earnings(self, seller, *orders):
        for order in orders:
            if order and order.status == Order.Status.PAID:
                SellerEarning.objects.get_or_create(
                    order=order,
                    defaults={
                        "seller": seller,
                        "gross": order.amount,
                        "commission": 0,
                        "net": order.amount,
                    },
                )

    # ── Reviews ───────────────────────────────────────────────────────────────

    def _ensure_review(self, order, product, rating, body):
        ProductReview.objects.get_or_create(
            order=order,
            defaults={
                "product": product,
                "rating": rating,
                "text": body,
                "is_published": True,
            },
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _ensure_customer(self, email):
        user, created = User.objects.get_or_create(email=email, defaults={"is_active": True})
        if created:
            user.set_password("demo1234!")
            user.save()
        customer, _ = Customer.objects.get_or_create(user=user)
        wallet, _ = Wallet.objects.get_or_create(customer=customer)
        return user, customer, wallet

    def _credit_topup(self, wallet, customer, amount, ref):
        topup, created = TopUp.objects.get_or_create(
            gateway_ref=ref,
            defaults={
                "customer": customer, "amount": amount, "bonus": 0,
                "gateway": TopUp.Gateway.DUITKU, "status": TopUp.Status.PAID,
            },
        )
        if created:
            entry = credit(wallet, amount=amount, entry_type="topup",
                           ref=f"topup:{topup.public_id}", note=f"Demo top-up Rp{amount:,}")
            topup.ledger_entry = entry
            topup.save(update_fields=["ledger_entry", "updated_at"])

    def _entry_exists(self, ref):
        from apps.wallet.models import LedgerEntry
        return LedgerEntry.objects.filter(ref=ref).exists()

    def _buy_plan(self, customer, wallet, plan, order_ref, sub_days,
                  coupon=None, pwyw_price=None, existing_sub=None, existing_lic=None):
        order = Order.objects.filter(idempotency_key=order_ref).first()
        if order is None:
            discount = 0
            if coupon:
                valid, _ = coupon.is_valid_for(plan)
                if valid:
                    discount = coupon.compute_discount(plan.price)

            if pwyw_price is not None and plan.pwyw:
                effective_amount = max(int(pwyw_price), plan.min_price or 0)
            else:
                effective_amount = max(0, plan.price - discount)

            wallet.refresh_from_db()
            if wallet.balance < effective_amount:
                self.stdout.write(self.style.WARNING(
                    f"    Skipping order {order_ref}: balance Rp{wallet.balance:,} < Rp{effective_amount:,}"
                ))
                sub = Subscription.objects.filter(customer=customer, plan=plan).first()
                lic = License.objects.filter(customer=customer, plan=plan).first()
                return None, sub, lic

            order = Order.objects.create(
                customer=customer, plan=plan, amount=effective_amount,
                status=Order.Status.PAID, idempotency_key=order_ref,
                coupon=coupon if discount > 0 else None, discount=discount,
            )
            if effective_amount > 0 and not self._entry_exists(f"order:{order.public_id}"):
                wallet.refresh_from_db()
                entry = debit(wallet, amount=effective_amount, entry_type="purchase",
                              ref=f"order:{order.public_id}", note=f"{plan.name} purchase")
                order.ledger_entry = entry
                order.save(update_fields=["ledger_entry", "updated_at"])
            if coupon and discount > 0:
                from django.db.models import F
                Coupon.objects.filter(pk=coupon.pk).update(used_count=F("used_count") + 1)

        # Subscription
        if existing_sub:
            sub = existing_sub
            now = timezone.now()
            sub.current_period_end = now + timedelta(days=max(sub_days, 1))
            sub.save(update_fields=["current_period_end", "updated_at"])
        else:
            sub = Subscription.objects.filter(
                customer=customer, plan=plan,
            ).exclude(status=Subscription.Status.CANCELLED).first()
            if sub is None and plan.interval != Plan.Interval.NONE:
                period_end = timezone.now() + timedelta(days=max(sub_days, 1) if sub_days > 0 else 1)
                sub = Subscription.objects.create(
                    customer=customer, plan=plan,
                    status=Subscription.Status.ACTIVE,
                    current_period_end=period_end,
                )
                if order:
                    order.subscription = sub
                    order.save(update_fields=["subscription", "updated_at"])

        # Grant + License (only for LICENSE_KEY deliverables)
        if existing_lic:
            lic = existing_lic
        else:
            lic = License.objects.filter(customer=customer, plan=plan).exclude(
                status=License.Status.REVOKED
            ).first()
            if lic is None:
                deliverable = plan.deliverables.filter(type=Deliverable.Type.LICENSE_KEY).first()
                if deliverable and order:
                    grant = Grant.objects.create(
                        customer=customer, order=order, subscription=sub,
                        deliverable=deliverable, type=Deliverable.Type.LICENSE_KEY,
                        status=Grant.Status.ACTIVE, payload={},
                    )
                    lic = License.objects.create(
                        customer=customer, plan=plan, subscription=sub,
                        grant=grant, status=License.Status.ACTIVE,
                        seat_limit=plan.seat_limit,
                    )
                    grant.payload = {"license_id": lic.pk}
                    grant.save(update_fields=["payload", "updated_at"])

                # For COURSE deliverable — create Grant
                course_deliv = plan.deliverables.filter(type=Deliverable.Type.COURSE).first()
                if course_deliv and order:
                    Grant.objects.get_or_create(
                        customer=customer, order=order,
                        defaults={
                            "subscription": sub,
                            "deliverable": course_deliv,
                            "type": Deliverable.Type.COURSE,
                            "status": Grant.Status.ACTIVE,
                            "payload": {"product_id": plan.product_id, "product_name": plan.product.name},
                        },
                    )

                # For DOWNLOAD
                file_deliv = plan.deliverables.filter(type=Deliverable.Type.DOWNLOAD).first()
                if file_deliv and order:
                    Grant.objects.get_or_create(
                        customer=customer, order=order,
                        defaults={
                            "deliverable": file_deliv,
                            "type": Deliverable.Type.DOWNLOAD,
                            "status": Grant.Status.ACTIVE,
                            "payload": file_deliv.config or {},
                        },
                    )

        return order, sub, lic

    # ── Google SocialApp ──────────────────────────────────────────────────────

    def _seed_google_app(self):
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        if not client_id:
            self.stdout.write(self.style.WARNING("  GOOGLE_CLIENT_ID not set — skipping Google SocialApp"))
            return
        try:
            from allauth.socialaccount.models import SocialApp
            site = Site.objects.get_current()
            app, created = SocialApp.objects.get_or_create(
                provider="google",
                defaults={"name": "Google", "client_id": client_id, "secret": client_secret},
            )
            if not created:
                app.client_id = client_id
                app.secret = client_secret
                app.save(update_fields=["client_id", "secret"])
            app.sites.add(site)
            self.stdout.write(f"  Google SocialApp {'created' if created else 'updated'}")
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Google SocialApp error: {exc}"))
