import os
import sys

# Move to the correct directory to fix Django imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from apps.accounts.models import Seller
from apps.catalog.models import Product, Plan
from apps.provisioning.models import Entitlement, Deliverable

def run():
    print("Mempersiapkan data produk Support Desk di roc_estalatree...")
    
    # Get or create a default seller
    seller, _ = Seller.objects.get_or_create(
        slug='tokowebjaya',
        defaults={'name': 'Toko Web Jaya', 'wa_number': '628123456789'}
    )

    # 1. Create Product
    product, _ = Product.objects.get_or_create(
        slug="roc-support-desk",
        defaults={
            'seller': seller,
            'name': "RoC Support Desk (On-Premise)",
            'type': Product.Type.RECURRING,
            'visibility': Product.Visibility.PUBLIC,
            'description': "Enterprise-grade Helpdesk & Ticketing System with WhatsApp, E-Sign, and Project Management modules."
        }
    )

    # 4. Buat / Dapatkan Entitlements (Hak Akses Modul & Kuota)
    # A. Tingkat Plan
    ent_tier_starter, _ = Entitlement.objects.get_or_create(key="PLAN_TIER", value="starter", defaults={'name': "Starter Tier"})
    ent_tier_pro, _     = Entitlement.objects.get_or_create(key="PLAN_TIER", value="professional", defaults={'name': "Professional Tier"})
    ent_tier_ent, _     = Entitlement.objects.get_or_create(key="PLAN_TIER", value="enterprise", defaults={'name': "Enterprise Tier"})

    # B. Batas Agen (MAX_AGENTS)
    ent_agent_3, _  = Entitlement.objects.get_or_create(key="MAX_AGENTS", value="3", defaults={'name': "Maksimal 3 Agen"})
    ent_agent_10, _ = Entitlement.objects.get_or_create(key="MAX_AGENTS", value="10", defaults={'name': "Maksimal 10 Agen"})
    ent_agent_unlimited, _ = Entitlement.objects.get_or_create(key="MAX_AGENTS", value="999", defaults={'name': "Agen Unlimited"})

    # C. Fitur Modul (Modules)
    ent_wa_false, _ = Entitlement.objects.get_or_create(key="WHATSAPP", value="false", defaults={'name': "Tanpa WhatsApp"})
    ent_wa_true, _  = Entitlement.objects.get_or_create(key="WHATSAPP", value="true", defaults={'name': "WhatsApp Module Aktif"})
    
    ent_esign_false, _ = Entitlement.objects.get_or_create(key="ESIGN", value="false", defaults={'name': "Tanpa E-Sign"})
    ent_esign_true, _  = Entitlement.objects.get_or_create(key="ESIGN", value="true", defaults={'name': "E-Sign Module Aktif"})

    ent_project_false, _ = Entitlement.objects.get_or_create(key="PROJECT_MANAGEMENT", value="false", defaults={'name': "Tanpa Manajemen Proyek"})
    ent_project_true, _  = Entitlement.objects.get_or_create(key="PROJECT_MANAGEMENT", value="true", defaults={'name': "Manajemen Proyek Aktif"})

    # Helper function to create plan and assign entitlements
    def create_plan_variant(name, price, interval, seat_limit, sort_order, ents):
        plan, _ = Plan.objects.get_or_create(
            product=product,
            name=name,
            defaults={
                'seller': seller,
                'price': price,
                'interval': interval,
                'seat_limit': seat_limit,
                'sort_order': sort_order
            }
        )
        # Always create deliverable
        Deliverable.objects.get_or_create(
            plan=plan,
            type=Deliverable.Type.LICENSE_KEY,
            defaults={'instructions': "Terima kasih! Salin Kunci Lisensi ini dan tempelkan di dasbor aktivasi Support Desk Anda."}
        )
        plan.entitlements.clear()
        plan.entitlements.add(*ents)
        return plan

    # 2. Bikin Paket Berdasarkan Durasi dan Modul
    
    # --- MONTHLY PLANS ---
    create_plan_variant(
        name="Starter (Monthly)", price=150000, interval=Plan.Interval.MONTHLY, seat_limit=3, sort_order=10,
        ents=[ent_tier_starter, ent_agent_3, ent_wa_false, ent_esign_false, ent_project_false]
    )
    create_plan_variant(
        name="Professional (Monthly)", price=450000, interval=Plan.Interval.MONTHLY, seat_limit=10, sort_order=11,
        ents=[ent_tier_pro, ent_agent_10, ent_wa_true, ent_esign_true, ent_project_false]
    )
    create_plan_variant(
        name="Enterprise (Monthly)", price=1500000, interval=Plan.Interval.MONTHLY, seat_limit=999, sort_order=12,
        ents=[ent_tier_ent, ent_agent_unlimited, ent_wa_true, ent_esign_true, ent_project_true]
    )

    # --- YEARLY PLANS ---
    create_plan_variant(
        name="Starter (Yearly)", price=1500000, interval=Plan.Interval.YEARLY, seat_limit=3, sort_order=20,
        ents=[ent_tier_starter, ent_agent_3, ent_wa_false, ent_esign_false, ent_project_false]
    )
    create_plan_variant(
        name="Professional (Yearly)", price=4500000, interval=Plan.Interval.YEARLY, seat_limit=10, sort_order=21,
        ents=[ent_tier_pro, ent_agent_10, ent_wa_true, ent_esign_true, ent_project_false]
    )
    create_plan_variant(
        name="Enterprise (Yearly)", price=15000000, interval=Plan.Interval.YEARLY, seat_limit=999, sort_order=22,
        ents=[ent_tier_ent, ent_agent_unlimited, ent_wa_true, ent_esign_true, ent_project_true]
    )

    # --- ONE TIME FEE (PERPETUAL / LIFETIME) ---
    create_plan_variant(
        name="Lifetime Pro (One-Time)", price=15000000, interval=Plan.Interval.NONE, seat_limit=10, sort_order=30,
        ents=[ent_tier_pro, ent_agent_10, ent_wa_true, ent_esign_true, ent_project_false]
    )
    create_plan_variant(
        name="Lifetime Enterprise (One-Time)", price=35000000, interval=Plan.Interval.NONE, seat_limit=999, sort_order=31,
        ents=[ent_tier_ent, ent_agent_unlimited, ent_wa_true, ent_esign_true, ent_project_true]
    )

    print("✅ Berhasil! Produk 'RoC Support Desk' beserta variasi Monthly, Yearly, dan One-Time Fee telah ditambahkan ke roc_estalatree.")

if __name__ == "__main__":
    run()
