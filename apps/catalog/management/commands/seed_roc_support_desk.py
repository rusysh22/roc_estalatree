"""
Production catalog data for RoC Support Desk (github.com/rusysh22/roc_support_desk).

RoC Support Desk is a self-hosted, multi-channel IT helpdesk (WhatsApp + email +
web form ticketing, SLA tracking, dynamic form builder, knowledge base, e-sign)
that activates against this platform's /v1 API. Its own licensing/validators.py
reads two well-known entitlement keys — PLAN_TIER and MAX_AGENTS — plus one
entitlement per feature flag (true/false), falling back to its own
TIER_DEFAULT_FEATURES table only when the entitlements dict from the activation
response is completely empty. Every flag is therefore set explicitly here so a
customer's local install always reflects the plan they paid for.

Usage:
    uv run python manage.py seed_roc_support_desk

Idempotent — safe to rerun (get_or_create throughout).
"""
from django.core.management.base import BaseCommand

from apps.catalog.models import Plan, Product
from apps.provisioning.models import Deliverable, Entitlement
from apps.storefront.models import Block, StorePage

# (key, name, {plan_key: value, ...}) — value applied only to the listed plans.
FEATURE_MATRIX = [
    ("WHATSAPP", "WhatsApp channel (Evolution API)", {"starter": "true", "professional": "true", "business": "true", "enterprise": "true"}),
    ("EMAIL_SETTINGS", "Email channel (IMAP/SMTP)", {"starter": "true", "professional": "true", "business": "true", "enterprise": "true"}),
    ("FORM_BUILDER", "Dynamic form builder", {"starter": "true", "professional": "true", "business": "true", "enterprise": "true"}),
    ("KB_MANAGE", "Knowledge base management", {"starter": "true", "professional": "true", "business": "true", "enterprise": "true"}),
    ("SHORT_LINKS", "Short links", {"starter": "true", "professional": "true", "business": "true", "enterprise": "true"}),
    ("ANALYTICS", "Analytics dashboard", {"starter": "false", "professional": "true", "business": "true", "enterprise": "true"}),
    ("COMPANY_UNITS", "Company/unit structure", {"starter": "false", "professional": "true", "business": "true", "enterprise": "true"}),
    ("SLA_REPORTS", "SLA reports", {"starter": "false", "professional": "true", "business": "true", "enterprise": "true"}),
    ("AUDIT_EXPORT", "Audit log export", {"starter": "false", "professional": "true", "business": "true", "enterprise": "true"}),
    ("ESIGN", "Document e-signature", {"starter": "false", "professional": "true", "business": "true", "enterprise": "true"}),
    ("SHARED_DOCS", "Shared documents", {"starter": "false", "professional": "true", "business": "true", "enterprise": "true"}),
    ("PROJECT_MANAGEMENT", "Project management module", {"starter": "false", "professional": "true", "business": "true", "enterprise": "true"}),
    ("API_ACCESS", "REST API access", {"starter": "false", "professional": "false", "business": "true", "enterprise": "true"}),
]

# plan_key -> (display name, price IDR, interval, max_agents)
PLAN_SPECS = {
    "starter": ("Starter", 149_000, Plan.Interval.MONTHLY, 3),
    "professional": ("Professional", 349_000, Plan.Interval.MONTHLY, 10),
    "business": ("Business", 699_000, Plan.Interval.MONTHLY, 25),
    "enterprise": ("Enterprise", 9_999_000, Plan.Interval.YEARLY, 999),
}

# plan_key -> storefront bullet list. Rendered by product.html as a checkmark
# list; a value of "true" shows the key alone, any other value shows "key: value".
PLAN_FEATURES = {
    "starter": {
        "WhatsApp, email, and web form ticket intake": "true",
        "Kanban ticket board": "true",
        "Dynamic form builder": "true",
        "Knowledge base": "true",
    },
    "professional": {
        "Everything in Starter": "true",
        "Analytics dashboard": "true",
        "SLA reports and audit log export": "true",
        "Document e-sign": "true",
        "Project management module": "true",
    },
    "business": {
        "Everything in Professional": "true",
        "Full REST API access": "true",
    },
    "enterprise": {
        "Everything in Business": "true",
        "Priority onboarding": "true",
        "Annual billing": "true",
    },
}


class Command(BaseCommand):
    help = "Create the RoC Support Desk product, plans, and activation entitlements (idempotent)."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding RoC Support Desk product…"))
        product = self._seed_product()
        plans = self._seed_plans(product)
        self._seed_entitlements(plans)
        self._seed_storefront_block(product)
        self.stdout.write(self.style.SUCCESS("\nRoC Support Desk product ready."))

    def _seed_product(self):
        product, created = Product.objects.get_or_create(
            slug="roc-support-desk",
            defaults={
                "name": "RoC Support Desk",
                "type": Product.Type.RECURRING,
                "visibility": Product.Visibility.PUBLIC,
                "description": (
                    "Self-hosted, multi-channel IT helpdesk. Turn WhatsApp messages, "
                    "inbound email, and public web forms into tracked tickets with a "
                    "Kanban board, SLA timers, a drag-and-drop dynamic form builder, "
                    "a knowledge base, and document e-signature. License activation, "
                    "renewal, and feature gating are managed through this platform — "
                    "install once, then just keep your subscription active."
                ),
                "purchase_button_label": "Choose a Plan",
            },
        )
        self.stdout.write(f"  Product 'roc-support-desk' {'created' if created else 'OK'}")
        return product

    def _seed_plans(self, product):
        plans = {}
        for key, (name, price, interval, max_agents) in PLAN_SPECS.items():
            plan, created = Plan.objects.get_or_create(
                product=product,
                name=name,
                defaults={
                    "price": price,
                    "interval": interval,
                    "seat_limit": max_agents,
                    "sort_order": list(PLAN_SPECS).index(key),
                    "is_active": True,
                    "features": PLAN_FEATURES[key],
                },
            )
            if not created and plan.features != PLAN_FEATURES[key]:
                plan.features = PLAN_FEATURES[key]
                plan.save(update_fields=["features", "updated_at"])
            Deliverable.objects.get_or_create(
                plan=plan, type=Deliverable.Type.LICENSE_KEY, defaults={"config": {}}
            )
            plans[key] = plan
            self.stdout.write(
                f"  Plan '{name}' (Rp{price:,}/{interval}, {max_agents} agents) {'created' if created else 'OK'}"
            )
        return plans

    def _seed_entitlements(self, plans):
        # PLAN_TIER — one row per plan, value = the plan's own key.
        for key, plan in plans.items():
            ent, _ = Entitlement.objects.get_or_create(
                key="PLAN_TIER", value=key, defaults={"name": "Plan tier"}
            )
            ent.plans.add(plan)

        # MAX_AGENTS — one row per distinct seat limit.
        for key, plan in plans.items():
            max_agents = PLAN_SPECS[key][3]
            ent, _ = Entitlement.objects.get_or_create(
                key="MAX_AGENTS", value=str(max_agents), defaults={"name": "Max agent seats"}
            )
            ent.plans.add(plan)

        # Feature flags — one row per (key, value) pair, attached to every plan that shares it.
        for key, name, by_plan in FEATURE_MATRIX:
            for value in set(by_plan.values()):
                ent, _ = Entitlement.objects.get_or_create(
                    key=key, value=value, defaults={"name": name}
                )
                for plan_key, plan_value in by_plan.items():
                    if plan_value == value:
                        ent.plans.add(plans[plan_key])

        total = Entitlement.objects.filter(plans__in=plans.values()).distinct().count()
        self.stdout.write(f"  Entitlements: {total} distinct (key, value) rows attached across 4 plans")

    def _seed_storefront_block(self, product):
        store, created = StorePage.objects.get_or_create(
            slug="home",
            defaults={
                "title": "Berlanggan",
                "description": "Digital products and software licenses.",
                "is_published": True,
            },
        )
        self.stdout.write(f"  StorePage 'home' {'created' if created else 'OK'}")

        if not Block.objects.filter(store_page=store, product=product).exists():
            next_pos = (
                Block.objects.filter(store_page=store).order_by("-position").values_list(
                    "position", flat=True
                ).first()
                or 0
            )
            Block.objects.create(
                store_page=store, type=Block.Type.PRODUCT, position=next_pos + 1, product=product
            )
            self.stdout.write("  Storefront block for RoC Support Desk created")
        else:
            self.stdout.write("  Storefront block for RoC Support Desk OK")
