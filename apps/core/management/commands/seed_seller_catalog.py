"""Seed a rich 15-product catalog for the "Demo Seller Store" seller.

Usage:
    python manage.py seed_seller_catalog

Requires the demo seller (run `seed_accounts` first). Idempotent — safe to rerun.

Creates, all owned by SellerProfile(slug="demo-seller"):
  * 15 Products across every type (one-time / recurring / contact), 3 of them
    hidden (1 draft, 2 unlisted) so visibility filtering is testable.
  * 1–3 Plans per product with real prices, sale prices, PWYW, stock limits,
    seat limits and Duration Plan discount tiers (incl. a 0 %% "just longer"
    tier to exercise the optional-discount path).
  * Deliverables (download / license_key / credentials / api_key / course /
    access_link / manual) with config + post-purchase instructions.
  * Feature entitlements on the SaaS-style products.
  * Checkout intake questions on a couple of products.
  * Seller-scoped coupons (percent + fixed, one plan-restricted).
  * A published StorePage with heading + product blocks.
  * A handful of real paid orders + published reviews from customer@demo.test
    (funded automatically) so Orders / Earnings / ratings aren't empty.
"""
from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import Customer, SellerProfile, User
from apps.billing.models import Coupon
from apps.catalog.models import (
    CourseLesson,
    CourseModule,
    Plan,
    Product,
    ProductQuestion,
    ProductReview,
)
from apps.provisioning.models import Deliverable, Entitlement
from apps.storefront.models import Block, StorePage


# ── Catalog definition ───────────────────────────────────────────────────────
# Each product: dict with plans[]; each plan: dict with a deliverable + extras.

CATALOG: list[dict] = [
    {
        "slug": "notion-productivity-os",
        "name": "Notion Ultimate Productivity OS",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.PUBLIC,
        "button": "Get the template",
        "description": (
            "A complete life & work management system in Notion. A task manager, "
            "notes, goal tracker, habit tracker, project hub, and personal CRM in one "
            "connected dashboard.\n\n"
            "Includes 40+ ready-made pages, a video setup guide, and lifetime updates."
        ),
        "questions": [
            ("Your Notion email (to share the template)", "email", True),
            ("How did you hear about this product? (optional)", "text", False),
        ],
        "plans": [
            {
                "name": "Personal", "price": 149_000, "sale_price": 249_000, "sort": 0,
                "features": ["40+ pages", "Lifetime updates", "Video guide"],
                "deliverable": ("download", {"download_url": "https://example.com/files/notion-os-personal.zip"},
                                "Open the link, click 'Duplicate' in the top right to copy it into your Notion workspace."),
            },
            {
                "name": "Team", "price": 349_000, "sort": 1, "seats": 10,
                "features": ["Everything in Personal", "Team collaboration workspace", "30-minute onboarding call"],
                "deliverable": ("download", {"download_url": "https://example.com/files/notion-os-team.zip"},
                                "Duplicate the template, then invite your team members to the workspace."),
            },
        ],
    },
    {
        "slug": "saas-analytics-pro",
        "name": "Berlanggan Analytics Pro",
        "type": Product.Type.RECURRING,
        "visibility": Product.Visibility.PUBLIC,
        "button": "Start subscription",
        "description": (
            "A real-time analytics dashboard for your digital product: conversion funnels, "
            "retention, cohorts, and revenue attribution — no data team required.\n\n"
            "Automatic license activation, multi-seat, and an API for integrations."
        ),
        "plans": [
            {
                "name": "Starter", "price": 99_000, "interval": Plan.Interval.MONTHLY, "sort": 0, "seats": 1,
                "duration_discounts": {"3": 5, "6": 10, "12": 20},
                "features": ["1 seat", "30 days of history", "Email support"],
                "entitlements": [("MAX_PROJECTS", "3"), ("DATA_RETENTION_DAYS", "30")],
                "deliverable": ("license_key", {"seat_limit": 1},
                                "Activation: open the app > Settings > License > paste your license key."),
            },
            {
                "name": "Pro", "price": 249_000, "interval": Plan.Interval.MONTHLY, "sort": 1, "seats": 5,
                "duration_discounts": {"3": 5, "6": 12, "12": 22},
                "features": ["5 seats", "1 year of history", "Priority support", "CSV/PDF export"],
                "entitlements": [("MAX_PROJECTS", "25"), ("DATA_RETENTION_DAYS", "365"), ("PRO_EXPORT", "")],
                "deliverable": ("license_key", {"seat_limit": 5}, "Share one license key across up to 5 team devices."),
            },
            {
                "name": "Business", "price": 599_000, "interval": Plan.Interval.MONTHLY, "sort": 2, "seats": 20,
                "duration_discounts": {"6": 15, "12": 25},
                "features": ["20 seats", "Unlimited history", "4-hour SLA", "SSO", "Full API access"],
                "entitlements": [("MAX_PROJECTS", "unlimited"), ("DATA_RETENTION_DAYS", "3650"),
                                 ("PRO_EXPORT", ""), ("API_ACCESS", "")],
                "deliverable": ("license_key", {"seat_limit": 20}, "Contact us for SSO provisioning."),
            },
        ],
    },
    {
        "slug": "lightroom-preset-cinematic",
        "name": "Lightroom Preset Bundle — Cinematic",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.PUBLIC,
        "description": (
            "45 cinematic-style Lightroom presets for travel, portrait, and urban photos. "
            "Compatible with Lightroom Mobile & Desktop (.xmp + .dng files). Buy once, use forever."
        ),
        "plans": [
            {
                "name": "Full Bundle", "price": 79_000, "sale_price": 129_000, "sort": 0, "stock": 200,
                "features": ["45 presets .xmp + .dng", "PDF install guide", "Free v2 update"],
                "deliverable": ("download", {"download_url": "https://example.com/files/cinematic-presets.zip"},
                                "Extract the ZIP. Mobile: import the .dng files into Lightroom, then save them as presets."),
            },
        ],
    },
    {
        "slug": "copywriting-masterclass-2025",
        "name": "Copywriting Masterclass 2025",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.PUBLIC,
        "button": "Start learning",
        "description": (
            "A 6-module video course on writing copy that sells — from headlines, hooks, "
            "and storytelling to CTAs. Includes a swipe file of 50 copy examples and templates.\n\n"
            "Lifetime access + an alumni discussion group."
        ),
        "plans": [
            {
                "name": "Full Access", "price": 399_000, "sale_price": 599_000, "sort": 0,
                "features": ["6 video modules", "50-copy swipe file", "Certificate", "Alumni group"],
                "deliverable": ("course", {}, "Access the material via the 'My Products' menu in your dashboard."),
                "course": True,
            },
            {
                "name": "Community Only", "price": 99_000, "sort": 1,
                "features": ["Alumni discussion group", "Monthly Q&A recordings"],
                "deliverable": ("manual", {}, "The Telegram group invite is sent manually within 24 hours."),
            },
        ],
    },
    {
        "slug": "instagram-content-calendar",
        "name": "Instagram Content Calendar Template",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.PUBLIC,
        "button": "Name your price",
        "description": (
            "A 90-day content calendar template (Google Sheets + Notion): post ideas, caption "
            "hooks, hashtag research, and a performance tracker. Pay what you want, minimum Rp25,000."
        ),
        "plans": [
            {
                "name": "Pay What You Want", "price": 0, "sort": 0, "pwyw": True, "min_price": 25_000,
                "features": ["Google Sheets + Notion", "90 days of content slots", "100 caption hooks"],
                "deliverable": ("access_link", {"access_url": "https://example.com/unlock/ig-calendar"},
                                "Click the access link to make a copy of the template."),
            },
        ],
    },
    {
        "slug": "figma-design-system-kit",
        "name": "Figma Design System Kit",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.PUBLIC,
        "description": (
            "A production-ready design system for Figma: 60+ components, design tokens, "
            "auto-layout, dark mode, and documentation. Great for startups & agencies."
        ),
        "plans": [
            {
                "name": "Solo", "price": 199_000, "sort": 0,
                "features": ["60+ components", "Design tokens", "Light & dark mode"],
                "deliverable": ("download", {"download_url": "https://example.com/files/figma-ds-solo.fig"},
                                "Import the .fig file into your Figma (File > Import)."),
            },
            {
                "name": "Studio", "price": 499_000, "sort": 1, "seats": 8,
                "features": ["Everything in Solo", "8-person team license", "3 months of priority updates", "Tokens Studio source file"],
                "entitlements": [("TEAM_LICENSE", "8")],
                "deliverable": ("download", {"download_url": "https://example.com/files/figma-ds-studio.zip"},
                                "The Tokens Studio JSON file is included in the ZIP."),
            },
        ],
    },
    {
        "slug": "ai-prompt-vault",
        "name": "AI Prompt Vault — 2000+ Prompts",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.PUBLIC,
        "description": (
            "A collection of 2000+ ready-to-use prompts for ChatGPT, Claude, and Midjourney — "
            "categorized for marketing, coding, research, design, and productivity. "
            "Updated every month."
        ),
        "plans": [
            {
                "name": "Lifetime Access", "price": 59_000, "sale_price": 99_000, "sort": 0,
                "features": ["2000+ prompts", "Monthly updates", "Notion + PDF"],
                "deliverable": ("access_link", {"access_url": "https://example.com/unlock/prompt-vault"},
                                "The link opens a Notion database — bookmark it to get updates."),
            },
        ],
    },
    {
        "slug": "hosting-reseller-panel",
        "name": "Web Hosting Reseller Panel",
        "type": Product.Type.RECURRING,
        "visibility": Product.Visibility.PUBLIC,
        "description": (
            "A white-label hosting reseller panel: build your own packages, manage clients, "
            "and automate billing. cPanel/WHM access is provided via credentials."
        ),
        "plans": [
            {
                "name": "Bronze", "price": 149_000, "interval": Plan.Interval.MONTHLY, "sort": 0,
                "duration_discounts": {"6": 10, "12": 15},
                "features": ["25 GB SSD", "25 cPanel accounts", "Ticket support"],
                "deliverable": ("credentials", {"username": "reseller_bronze", "password": "ChangeMe#Bronze1"},
                                "Log in to WHM at https://panel.example.com:2087 with these credentials, then change the password."),
            },
            {
                "name": "Silver", "price": 349_000, "interval": Plan.Interval.MONTHLY, "sort": 1,
                "duration_discounts": {"6": 10, "12": 18},
                "features": ["100 GB SSD", "100 cPanel accounts", "Priority support", "Free migration"],
                "deliverable": ("credentials", {"username": "reseller_silver", "password": "ChangeMe#Silver1"},
                                "Log in to WHM, then change the password immediately under 'Password & Security'."),
            },
            {
                "name": "Gold", "price": 799_000, "interval": Plan.Interval.MONTHLY, "sort": 2,
                "duration_discounts": {"6": 12, "12": 22},
                "features": ["Unlimited SSD", "Unlimited accounts", "24/7 support", "Dedicated IP"],
                "deliverable": ("credentials", {"username": "reseller_gold", "password": "ChangeMe#Gold1"},
                                "The dedicated IP is sent separately by email within 24 hours."),
            },
        ],
    },
    {
        "slug": "stock-video-pack-4k",
        "name": "Premium Stock Video Pack 4K",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.PUBLIC,
        "description": (
            "120 royalty-free 4K stock video clips: nature, lifestyle, technology, and "
            "abstract. Commercial license included. About 14 GB total."
        ),
        "plans": [
            {
                "name": "Commercial License", "price": 249_000, "sort": 0, "stock": 50,
                "features": ["120 4K clips", "Commercial license", "Royalty-free forever"],
                "deliverable": ("download", {"download_url": "https://example.com/files/stock-video-4k-pack.zip"},
                                "Large file (about 14 GB) — use a stable connection / a download manager."),
            },
        ],
    },
    {
        "slug": "discord-community-bot",
        "name": "Discord Community Bot — Pro",
        "type": Product.Type.RECURRING,
        "visibility": Product.Visibility.PUBLIC,
        "description": (
            "A Discord bot for communities: auto-moderation, leveling, welcome messages, "
            "giveaways, and support tickets. Activated with an API key."
        ),
        "plans": [
            {
                "name": "Monthly", "price": 89_000, "interval": Plan.Interval.MONTHLY, "sort": 0,
                # Includes a 0 %% tier — "prepay longer, no discount" (Duration Plan optional discount)
                "duration_discounts": {"3": 0, "6": 8, "12": 17},
                "features": ["1 server", "All modules", "Automatic updates"],
                "entitlements": [("MAX_SERVERS", "1")],
                "deliverable": ("api_key", {"api_key": "dcb_live_" + uuid.uuid4().hex[:24]},
                                "Enter the API key when adding the bot via the dashboard at https://bot.example.com."),
            },
            {
                "name": "Yearly", "price": 890_000, "interval": Plan.Interval.YEARLY, "sort": 1,
                "features": ["3 servers", "All modules", "Priority uptime", "Save 2 months"],
                "entitlements": [("MAX_SERVERS", "3")],
                "deliverable": ("api_key", {"api_key": "dcb_live_" + uuid.uuid4().hex[:24]},
                                "One API key works for up to 3 servers."),
            },
        ],
    },
    {
        "slug": "personal-finance-tracker",
        "name": "Personal Finance Tracker (Spreadsheet)",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.PUBLIC,
        "description": (
            "A personal finance tracking spreadsheet: 50/30/20 budgeting, net worth, "
            "monthly cash flow, and savings goals — automated with charts. "
            "Google Sheets & Excel."
        ),
        "plans": [
            {
                "name": "Standard", "price": 49_000, "sort": 0,
                "features": ["Google Sheets + Excel", "Automatic dashboard", "Video tutorial"],
                "deliverable": ("download", {"download_url": "https://example.com/files/finance-tracker.xlsx"},
                                "Google Sheets: File > Make a copy. Excel: enable macros if prompted."),
            },
        ],
    },
    {
        "slug": "freelance-contract-templates",
        "name": "Freelance Contract Templates (Legal Pack)",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.PUBLIC,
        "description": (
            "12 ready-to-use freelance contract templates (English & Indonesian): "
            "work agreement, NDA, invoice, scope of work, and revisions. .docx & PDF format. "
            "Prepared with a legal consultant."
        ),
        "plans": [
            {
                "name": "Complete Pack", "price": 129_000, "sale_price": 199_000, "sort": 0,
                "features": ["12 templates", "EN + ID", ".docx & PDF", "Fill-in guide"],
                "deliverable": ("download", {"download_url": "https://example.com/files/freelance-contracts.zip"},
                                "These are general templates, not legal advice. Adapt them to your needs."),
            },
        ],
    },
    {
        "slug": "portfolio-review-1on1",
        "name": "1-on-1 Portfolio Review",
        "type": Product.Type.CONTACT,
        "visibility": Product.Visibility.PUBLIC,
        "button": "Chat on WhatsApp",
        "wa_number": "628111111111",
        "description": (
            "A 45-minute portfolio review over Google Meet. Honest feedback on your "
            "positioning, case studies, and what's holding you back from landing clients. "
            "Message on WhatsApp to schedule."
        ),
        "plans": [],
    },
    {
        "slug": "digital-marketing-fundamentals",
        "name": "Course: Digital Marketing Fundamentals",
        "type": Product.Type.ONE_TIME,
        "visibility": Product.Visibility.UNLISTED,
        "description": (
            "An 8-module course for beginners: SEO, social media, ads, email marketing, and "
            "analytics. Local brand case studies + campaign templates. (Unlisted — early access)"
        ),
        "plans": [
            {
                "name": "Early Access", "price": 549_000, "sale_price": 899_000, "sort": 0,
                "features": ["8 video modules", "Campaign templates", "2025 material updates", "Alumni group"],
                "deliverable": ("course", {}, "Access via 'My Products'. New modules release every week."),
                "course": True,
            },
        ],
    },
    {
        "slug": "managed-vps-starter-cloud",
        "name": "Managed VPS — Starter Cloud",
        "type": Product.Type.RECURRING,
        "visibility": Product.Visibility.PUBLIC,
        "description": (
            "A managed VPS with setup, patching, daily backups, and monitoring handled by "
            "our team. Great for small-to-midsize web apps. Manual provisioning within "
            "one business day."
        ),
        "plans": [
            {
                "name": "1 GB RAM", "price": 75_000, "interval": Plan.Interval.MONTHLY, "sort": 0,
                "duration_discounts": {"3": 5, "6": 12, "12": 20},
                "features": ["1 vCPU / 1 GB RAM", "25 GB NVMe", "Daily backups", "Monitoring"],
                "deliverable": ("manual", {}, "SSH access details are emailed once the server is ready (within one business day)."),
            },
            {
                "name": "2 GB RAM", "price": 145_000, "interval": Plan.Interval.MONTHLY, "sort": 1,
                "duration_discounts": {"3": 5, "6": 12, "12": 20},
                "features": ["2 vCPU / 2 GB RAM", "50 GB NVMe", "Daily backups", "Free SSL & setup"],
                "deliverable": ("manual", {}, "Include your domain at checkout so we can set up SSL at the same time."),
            },
            {
                "name": "4 GB RAM", "price": 280_000, "interval": Plan.Interval.MONTHLY, "sort": 2,
                "duration_discounts": {"6": 15, "12": 25},
                "features": ["4 vCPU / 4 GB RAM", "80 GB NVMe", "Backups twice daily", "Priority support"],
                "deliverable": ("manual", {}, "Migration from your old provider is free — just reply to the onboarding email."),
            },
        ],
    },
]

# ── Purchases to seed (idempotency key, product slug, plan name, duration) ────
DEMO_PURCHASES = [
    ("notion-productivity-os", "Personal", 1, 5, "The template is really well organized — I started using it for daily work right away."),
    ("lightroom-preset-cinematic", "Full Bundle", 1, 5, "Moody colors that stay consistent across different lighting conditions."),
    ("copywriting-masterclass-2025", "Full Access", 1, 4, "Dense material — the swipe file alone is worth it."),
    ("ai-prompt-vault", "Lifetime Access", 1, 5, "I use it constantly, and the monthly updates are a bonus."),
    ("figma-design-system-kit", "Solo", 1, None, None),
    ("saas-analytics-pro", "Starter", 3, None, None),
]


class Command(BaseCommand):
    help = "Seed a 15-product catalog for the Demo Seller Store."

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            seller = SellerProfile.objects.get(slug="demo-seller")
        except SellerProfile.DoesNotExist:
            raise CommandError("Demo seller not found — run `python manage.py seed_accounts` first.")

        self.stdout.write(self.style.MIGRATE_HEADING("Seeding Demo Seller Store catalog…"))

        products = {}
        for spec in CATALOG:
            products[spec["slug"]] = self._product(seller, spec)

        self._prune(seller, {s["slug"] for s in CATALOG})
        self._coupons(seller, products)
        self._store(seller, products)
        self._purchases(seller, products)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone — {Product.objects.filter(seller=seller).count()} products, "
            f"{Plan.objects.filter(seller=seller).count()} plans for /{seller.slug}/"
        ))

    def _prune(self, seller, keep_slugs):
        """Drop seed products no longer in CATALOG (only if they have no orders)."""
        from apps.billing.models import Order
        stale = Product.objects.filter(seller=seller).exclude(slug__in=keep_slugs)
        for product in stale:
            if Order.objects.filter(plan__product=product).exists():
                self.stdout.write(f"  keep (has orders): {product.slug}")
                continue
            Block.objects.filter(product=product).delete()
            Deliverable.objects.filter(plan__product=product).delete()
            product.plans.all().delete()
            product.modules.all().delete()
            product.delete()
            self.stdout.write(f"  pruned: {product.slug}")

    # ── Product + plans ─────────────────────────────────────────────────────

    def _product(self, seller, spec):
        from apps.core.images import make_placeholder

        product, _ = Product.objects.get_or_create(
            slug=spec["slug"],
            defaults={
                "seller": seller,
                "name": spec["name"],
                "type": spec["type"],
                "visibility": spec["visibility"],
                "description": spec["description"],
                "wa_number": spec.get("wa_number", ""),
                "purchase_button_label": spec.get("button", ""),
            },
        )
        # keep key fields fresh on rerun
        Product.objects.filter(pk=product.pk).update(
            seller=seller, name=spec["name"], type=spec["type"],
            visibility=spec["visibility"], description=spec["description"],
            wa_number=spec.get("wa_number", ""),
            purchase_button_label=spec.get("button", ""),
        )
        if not product.cover_image:
            product.cover_image.save(f"{spec['slug']}.webp",
                                     make_placeholder(spec["name"], seed=spec["slug"]),
                                     save=True)

        for q_label, q_type, q_required in spec.get("questions", []):
            ProductQuestion.objects.get_or_create(
                product=product, label=q_label,
                defaults={"field_type": q_type, "required": q_required,
                          "sort_order": len(product.questions.all())},
            )

        for p in spec.get("plans", []):
            self._plan(seller, product, p)

        self.stdout.write(f"  {product.slug}  ({product.get_visibility_display()}, {len(spec.get('plans', []))} plan)")
        return product

    def _plan(self, seller, product, p):
        plan, _ = Plan.objects.get_or_create(
            product=product, name=p["name"],
            defaults={
                "seller": seller,
                "price": p["price"],
                "interval": p.get("interval", Plan.Interval.NONE),
                "seat_limit": p.get("seats", 1),
                "sort_order": p.get("sort", 0),
                "is_active": True,
                "sale_price": p.get("sale_price"),
                "pwyw": p.get("pwyw", False),
                "min_price": p.get("min_price", 0),
                "stock_quantity": p.get("stock"),
                "duration_discounts": p.get("duration_discounts", {}),
                "features": {f: "" for f in p.get("features", [])},
            },
        )
        Plan.objects.filter(pk=plan.pk).update(
            seller=seller, price=p["price"], interval=p.get("interval", Plan.Interval.NONE),
            seat_limit=p.get("seats", 1), sort_order=p.get("sort", 0),
            sale_price=p.get("sale_price"), pwyw=p.get("pwyw", False),
            min_price=p.get("min_price", 0), stock_quantity=p.get("stock"),
            duration_discounts=p.get("duration_discounts", {}),
            features={f: "" for f in p.get("features", [])},
        )

        d_type, d_config, d_instructions = p["deliverable"]
        deliverable, _ = Deliverable.objects.get_or_create(
            plan=plan, type=d_type,
            defaults={"config": d_config, "instructions": d_instructions},
        )
        Deliverable.objects.filter(pk=deliverable.pk).update(
            config=d_config, instructions=d_instructions
        )

        for key, value in p.get("entitlements", []):
            ent, _ = Entitlement.objects.get_or_create(
                key=key, value=value,
                defaults={"name": key.replace("_", " ").title()},
            )
            ent.plans.add(plan)

        if p.get("course"):
            self._course(product)
        return plan

    def _course(self, product):
        mods = [
            ("Module 1 — Foundations", [
                ("Introduction & mindset", "text", "Why this skill matters and how to learn it most effectively.", True),
                ("Opening case study", "video", "https://www.youtube.com/embed/dQw4w9WgXcQ", False),
            ]),
            ("Module 2 — Practice", [
                ("The core framework", "text", "Step by step, applying the framework to a real project.", False),
                ("Guided exercise (download)", "file", "https://example.com/files/exercise-module2.pdf", False),
            ]),
        ]
        for i, (title, lessons) in enumerate(mods):
            mod, _ = CourseModule.objects.get_or_create(
                product=product, title=title, defaults={"sort_order": i}
            )
            for j, (ltitle, ltype, content, preview) in enumerate(lessons):
                CourseLesson.objects.get_or_create(
                    module=mod, title=ltitle,
                    defaults={
                        "lesson_type": ltype,
                        "content": content if ltype in ("text", "video") else "",
                        "file_url": content if ltype == "file" else "",
                        "sort_order": j,
                        "is_preview": preview,
                    },
                )

    # ── Coupons ────────────────────────────────────────────────────────────

    def _coupons(self, seller, products):
        Coupon.objects.get_or_create(code="DEMOSTORE15", defaults={
            "seller": seller, "discount_type": Coupon.DiscountType.PERCENT,
            "value": 15, "max_discount": 100_000, "usage_limit": 0, "is_active": True,
        })
        Coupon.objects.get_or_create(code="SAVE30K", defaults={
            "seller": seller, "discount_type": Coupon.DiscountType.FIXED,
            "value": 30_000, "min_order": 100_000, "usage_limit": 200, "is_active": True,
        })
        c3, _ = Coupon.objects.get_or_create(code="ANALYTICS20", defaults={
            "seller": seller, "discount_type": Coupon.DiscountType.PERCENT,
            "value": 20, "max_discount": 150_000, "usage_limit": 100, "is_active": True,
        })
        c3.plans.set(Plan.objects.filter(product=products["saas-analytics-pro"]))
        self.stdout.write("  coupons: DEMOSTORE15, SAVE30K, ANALYTICS20 (plan-restricted)")

    # ── Store page + blocks ────────────────────────────────────────────────

    def _store(self, seller, products):
        store, _ = StorePage.objects.get_or_create(
            seller=seller,
            defaults={"slug": seller.slug, "title": seller.name, "is_published": True},
        )
        StorePage.objects.filter(pk=store.pk).update(
            slug=seller.slug, title=seller.name, is_published=True,
            description="Digital templates, tools, assets, and courses for creators & small businesses.",
        )

        Block.objects.filter(store_page=store).delete()
        Block.objects.create(store_page=store, type=Block.Type.HEADING, position=0,
                             config={"text": "✨ Featured digital products"})
        pos = 1
        for spec in CATALOG:
            prod = products[spec["slug"]]
            if prod.visibility == Product.Visibility.PUBLIC:
                Block.objects.create(store_page=store, type=Block.Type.PRODUCT,
                                     position=pos, product=prod)
                pos += 1
        self.stdout.write(f"  store page /{store.slug}/ published with {pos - 1} product blocks")

    # ── A few real paid orders + reviews ──────────────────────────────────

    def _purchases(self, seller, products):
        try:
            buyer = Customer.objects.get(user__email="customer@demo.test")
        except (Customer.DoesNotExist, User.DoesNotExist):
            self.stdout.write("  (skip purchases — customer@demo.test not found)")
            return

        from apps.billing.checkout import checkout
        from apps.wallet.models import LedgerEntry
        from apps.wallet.services import credit

        buyer.wallet.refresh_from_db()
        if buyer.wallet.balance < 3_000_000:
            credit(wallet=buyer.wallet, amount=3_000_000 - buyer.wallet.balance,
                   entry_type=LedgerEntry.Type.ADJUSTMENT,
                   ref=f"seed_catalog:{buyer.pk}", note="Seed: budget for demo purchases")

        made = 0
        for slug, plan_name, dm, rating, review_text in DEMO_PURCHASES:
            plan = Plan.objects.filter(product=products[slug], name=plan_name).first()
            if not plan:
                continue
            key = f"seedcat:{buyer.pk}:{slug}:{plan_name}"
            try:
                order, _grants, _url = checkout(
                    customer=buyer, plan=plan, checkout_key=key,
                    duration_multiplier=dm,
                    callback_url="http://localhost:8000/billing/webhook/sumopod/",
                    return_url="http://localhost:8000/orders/pending/",
                )
            except Exception as exc:  # noqa: BLE001 — seed script, keep going
                self.stdout.write(self.style.WARNING(f"  purchase {slug} skipped: {exc}"))
                continue
            made += 1
            if rating and order.status == order.Status.PAID:
                ProductReview.objects.get_or_create(
                    order=order,
                    defaults={"product": products[slug], "rating": rating,
                              "text": review_text, "is_published": True},
                )
        self.stdout.write(f"  seeded {made} paid orders from customer@demo.test (+reviews)")
