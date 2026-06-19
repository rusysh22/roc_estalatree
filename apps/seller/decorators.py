"""Access control decorators for the Seller Dashboard."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from apps.accounts.models import SellerProfile


def seller_required(view_func):
    """Gate: user must own an approved SellerProfile (or be superuser).

    Sets request.seller so views don't need to re-query.
    Superuser gets the first SellerProfile (single-merchant mode).
    """
    @wraps(view_func)
    @login_required(login_url="/accounts/login/")
    def _wrapped(request, *args, **kwargs):
        user = request.user

        if user.is_superuser:
            seller = SellerProfile.objects.filter(user=user).first()
            if seller is None:
                # Try to claim the platform's default unclaimed SellerProfile
                seller = SellerProfile.objects.filter(user__isnull=True).first()
                if seller is not None:
                    seller.user = user
                    seller.save(update_fields=["user", "updated_at"])
            if seller is None:
                # Auto-create a SellerProfile for the superuser on first access
                from django.utils.text import slugify
                base_slug = slugify(user.email.split("@")[0]) or "store"
                slug = base_slug
                n = 1
                while SellerProfile.objects.filter(slug=slug).exists():
                    slug = f"{base_slug}-{n}"
                    n += 1
                seller = SellerProfile.objects.create(
                    user=user,
                    name="My Store",
                    slug=slug,
                    is_active=True,
                    is_approved=True,
                )
            request.seller = seller
            return view_func(request, *args, **kwargs)

        try:
            seller = user.seller_profile
        except SellerProfile.DoesNotExist:
            return redirect("seller:apply")

        if not seller.is_approved:
            return redirect("seller:apply")

        request.seller = seller
        return view_func(request, *args, **kwargs)

    return _wrapped
