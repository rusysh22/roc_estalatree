"""Forms for the Seller Dashboard."""
from django import forms

from apps.accounts.models import SellerProfile
from apps.billing.models import Coupon
from apps.catalog.models import Plan, Product
from apps.provisioning.models import Deliverable, Entitlement
from apps.storefront.models import Block, StorePage


class SellerProfileForm(forms.ModelForm):
    class Meta:
        model = SellerProfile
        fields = ["name", "bio", "logo_url", "wa_number"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input-field"}),
            "bio": forms.Textarea(attrs={"class": "input-field", "rows": 3}),
            "logo_url": forms.URLInput(attrs={"class": "input-field"}),
            "wa_number": forms.TextInput(attrs={"class": "input-field", "placeholder": "628123456789"}),
        }


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "type", "visibility", "description", "cover_image_url", "wa_number"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input-field"}),
            "type": forms.Select(attrs={"class": "input-field"}),
            "visibility": forms.Select(attrs={"class": "input-field"}),
            "description": forms.Textarea(attrs={"class": "input-field", "rows": 4}),
            "cover_image_url": forms.URLInput(attrs={"class": "input-field", "placeholder": "https://..."}),
            "wa_number": forms.TextInput(attrs={"class": "input-field", "placeholder": "628123456789"}),
        }


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ["name", "price", "interval", "seat_limit", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input-field"}),
            "price": forms.NumberInput(attrs={"class": "input-field"}),
            "interval": forms.Select(attrs={"class": "input-field"}),
            "seat_limit": forms.NumberInput(attrs={"class": "input-field"}),
        }


class DeliverableForm(forms.ModelForm):
    class Meta:
        model = Deliverable
        fields = ["type", "config", "instructions"]
        widgets = {
            "type": forms.Select(attrs={"class": "input-field"}),
            "config": forms.Textarea(attrs={"class": "input-field font-mono text-xs", "rows": 4,
                                            "placeholder": '{"download_url": "https://..."}'}),
            "instructions": forms.Textarea(attrs={"class": "input-field", "rows": 3,
                                                  "placeholder": "e.g. Extract with password: abc123. Then run setup.exe."}),
        }


class EntitlementForm(forms.ModelForm):
    class Meta:
        model = Entitlement
        fields = ["key", "name", "value"]
        widgets = {
            "key": forms.TextInput(attrs={"class": "input-field", "placeholder": "PRO_EXPORT"}),
            "name": forms.TextInput(attrs={"class": "input-field", "placeholder": "Export to Pro formats"}),
            "value": forms.TextInput(attrs={"class": "input-field", "placeholder": "leave blank for flag-style"}),
        }


class StorePageForm(forms.ModelForm):
    class Meta:
        model = StorePage
        fields = ["title", "description", "avatar_url", "is_published"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "input-field"}),
            "description": forms.Textarea(attrs={"class": "input-field", "rows": 3}),
            "avatar_url": forms.URLInput(attrs={"class": "input-field"}),
        }


class BlockOrderForm(forms.Form):
    """Reorder blocks via drag-and-drop (HTMX post with positions)."""
    order = forms.CharField(widget=forms.HiddenInput())


class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = [
            "code", "discount_type", "value", "min_order", "max_discount",
            "usage_limit", "valid_from", "valid_until", "is_active", "plans",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "input-field uppercase"}),
            "discount_type": forms.Select(attrs={"class": "input-field"}),
            "value": forms.NumberInput(attrs={"class": "input-field"}),
            "min_order": forms.NumberInput(attrs={"class": "input-field"}),
            "max_discount": forms.NumberInput(attrs={"class": "input-field"}),
            "usage_limit": forms.NumberInput(attrs={"class": "input-field"}),
            "valid_from": forms.DateTimeInput(attrs={"class": "input-field", "type": "datetime-local"}),
            "valid_until": forms.DateTimeInput(attrs={"class": "input-field", "type": "datetime-local"}),
            "plans": forms.CheckboxSelectMultiple(),
        }


class BroadcastForm(forms.Form):
    SEGMENT_CHOICES = [
        ("all", "All customers"),
        ("active_sub", "Customers with active subscriptions"),
        ("no_sub", "Customers without subscriptions"),
    ]
    segment = forms.ChoiceField(choices=SEGMENT_CHOICES, widget=forms.Select(attrs={"class": "input-field"}))
    message = forms.CharField(
        widget=forms.Textarea(attrs={"class": "input-field", "rows": 4,
                                     "placeholder": "Hi {name}, ..."})
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(visibility=Product.Visibility.PUBLIC),
        required=False,
        empty_label="— All products —",
        widget=forms.Select(attrs={"class": "input-field"}),
    )
