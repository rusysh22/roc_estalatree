from typing import List, Dict, Any
from ninja import Router
from django.shortcuts import get_object_or_404
from apps.catalog.models import Product, Plan

router = Router(tags=["Catalog"])

@router.get("/products/{slug}/plans", response=List[Dict[str, Any]])
def get_product_plans(request, slug: str):
    product = get_object_or_404(Product, slug=slug, visibility=Product.Visibility.PUBLIC)
    plans = Plan.objects.filter(product=product).prefetch_related('entitlements').order_by('sort_order')
    
    result = []
    for plan in plans:
        ents = plan.entitlements.all()
        # group entitlements into a dict
        ent_dict = {e.key: e.value for e in ents}
        
        result.append({
            "id": plan.id,
            "name": plan.name,
            "price": str(plan.price),
            "interval": plan.interval,
            "seat_limit": plan.seat_limit,
            "sort_order": plan.sort_order,
            "entitlements": ent_dict,
            "checkout_url": f"/checkout/{plan.id}/"
        })
    
    return result
