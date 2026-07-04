"""Storefront signals: auto-provision a StorePage for every seller.

Keeps SellerProfile.store_page always resolvable so "Sold by" links, featured-seller
cards, and the dashboard "My Store" link never point at a 404.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="accounts.SellerProfile")
def create_store_page_for_seller(sender, instance, created, **kwargs):
    from apps.storefront.models import StorePage

    store_page, _created = StorePage.objects.get_or_create(
        slug=instance.slug,
        defaults={
            "title": instance.name,
            "description": instance.bio or "",
            "is_published": False,
            "seller": instance,
        },
    )
    if store_page.seller_id is None:
        store_page.seller = instance
        store_page.save(update_fields=["seller"])
