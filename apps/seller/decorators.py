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
                # Attach superuser to the platform's default SellerProfile
                seller = SellerProfile.objects.first()
                if seller is not None and seller.user is None:
                    seller.user = user
                    seller.save(update_fields=["user", "updated_at"])
            if seller is None:
                raise PermissionDenied
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
