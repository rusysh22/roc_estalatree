"""Forms for the Seller Dashboard."""
from django import forms

from apps.accounts.models import SellerProfile
from apps.billing.models import AffiliateLink, Coupon, SellerPayout
from apps.catalog.models import CourseLesson, CourseModule, Plan, Product, ProductQuestion
from apps.provisioning.models import Deliverable, Entitlement
from apps.storefront.models import Block, StorePage


class SellerProfileForm(forms.ModelForm):
    class Meta:
        model = SellerProfile
        fields = [
            "name", "bio", "logo_url", "wa_number",
            "payout_bank_name", "payout_account_number", "payout_account_name",
            "custom_domain", "ga_tracking_id", "fb_pixel_id",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input-field"}),
            "bio": forms.Textarea(attrs={"class": "input-field", "rows": 3}),
            "logo_url": forms.URLInput(attrs={"class": "input-field"}),
            "wa_number": forms.TextInput(attrs={"class": "input-field", "placeholder": "628123456789"}),
            "payout_bank_name": forms.TextInput(attrs={"class": "input-field", "placeholder": "BCA / BNI / Mandiri"}),
            "payout_account_number": forms.TextInput(attrs={"class": "input-field"}),
            "payout_account_name": forms.TextInput(attrs={"class": "input-field"}),
            "custom_domain": forms.TextInput(attrs={"class": "input-field", "placeholder": "shop.example.com"}),
            "ga_tracking_id": forms.TextInput(attrs={"class": "input-field", "placeholder": "G-XXXXXXXXXX"}),
            "fb_pixel_id": forms.TextInput(attrs={"class": "input-field", "placeholder": "123456789012345"}),
        }


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "type", "visibility", "description", "cover_image_url", "wa_number", "purchase_button_label"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input-field"}),
            "type": forms.Select(attrs={"class": "input-field"}),
            "visibility": forms.Select(attrs={"class": "input-field"}),
            "description": forms.Textarea(attrs={"class": "input-field", "rows": 4}),
            "cover_image_url": forms.URLInput(attrs={"class": "input-field", "placeholder": "https://..."}),
            "wa_number": forms.TextInput(attrs={"class": "input-field", "placeholder": "628123456789"}),
            "purchase_button_label": forms.TextInput(attrs={"class": "input-field", "placeholder": "Buy Now"}),
        }


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ["name", "price", "interval", "seat_limit", "is_active",
                  "sale_price", "pwyw", "min_price", "stock_quantity"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input-field"}),
            "price": forms.NumberInput(attrs={"class": "input-field"}),
            "interval": forms.Select(attrs={"class": "input-field"}),
            "seat_limit": forms.NumberInput(attrs={"class": "input-field"}),
            "sale_price": forms.NumberInput(attrs={"class": "input-field"}),
            "min_price": forms.NumberInput(attrs={"class": "input-field"}),
            "stock_quantity": forms.NumberInput(attrs={"class": "input-field"}),
        }


class ProductQuestionForm(forms.ModelForm):
    class Meta:
        model = ProductQuestion
        fields = ["label", "field_type", "required", "sort_order"]
        widgets = {
            "label": forms.TextInput(attrs={"class": "input-field", "placeholder": "e.g. Discord username"}),
            "field_type": forms.Select(attrs={"class": "input-field"}),
            "sort_order": forms.NumberInput(attrs={"class": "input-field"}),
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


class ThemeForm(forms.Form):
    LAYOUT_CHOICES = [
        ("default", "Default (list)"),
        ("grid", "Grid (2 columns)"),
        ("compact", "Compact"),
    ]
    primary_color = forms.CharField(
        max_length=7, initial="#4f46e5", required=False,
        widget=forms.TextInput(attrs={"type": "color", "class": "h-10 w-16 rounded border border-gray-300 cursor-pointer p-0.5"}),
        label="Primary color",
    )
    background_color = forms.CharField(
        max_length=7, initial="#f9fafb", required=False,
        widget=forms.TextInput(attrs={"type": "color", "class": "h-10 w-16 rounded border border-gray-300 cursor-pointer p-0.5"}),
        label="Background color",
    )
    banner_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={"class": "input-field", "placeholder": "https://..."}),
        label="Banner image URL",
    )
    layout = forms.ChoiceField(
        choices=LAYOUT_CHOICES,
        widget=forms.Select(attrs={"class": "input-field"}),
        initial="default",
    )


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


class CourseModuleForm(forms.ModelForm):
    class Meta:
        model = CourseModule
        fields = ["title", "sort_order"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "input-field", "placeholder": "Module title"}),
            "sort_order": forms.NumberInput(attrs={"class": "input-field"}),
        }


class CourseLessonForm(forms.ModelForm):
    class Meta:
        model = CourseLesson
        fields = ["title", "lesson_type", "content", "file_url", "sort_order", "is_preview"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "input-field", "placeholder": "Lesson title"}),
            "lesson_type": forms.Select(attrs={"class": "input-field"}),
            "content": forms.Textarea(attrs={"class": "input-field font-mono text-xs", "rows": 3,
                                             "placeholder": "Text content or YouTube embed URL"}),
            "file_url": forms.URLInput(attrs={"class": "input-field", "placeholder": "https://..."}),
            "sort_order": forms.NumberInput(attrs={"class": "input-field"}),
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


class PayoutRequestForm(forms.Form):
    amount = forms.IntegerField(
        min_value=50000,
        label="Withdrawal amount (Rp)",
        widget=forms.NumberInput(attrs={"class": "input-field", "placeholder": "Minimum Rp50,000"}),
    )


class AffiliateLinkForm(forms.ModelForm):
    class Meta:
        model = AffiliateLink
        fields = ["code", "commission_rate", "label", "product", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "input-field uppercase", "placeholder": "MYREF2024"}),
            "commission_rate": forms.NumberInput(attrs={"class": "input-field", "min": 1, "max": 50}),
            "label": forms.TextInput(attrs={"class": "input-field", "placeholder": "Internal label"}),
            "product": forms.Select(attrs={"class": "input-field"}),
        }

    def __init__(self, seller, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(seller=seller)
        self.fields["product"].required = False
        self.fields["product"].empty_label = "— All products —"
