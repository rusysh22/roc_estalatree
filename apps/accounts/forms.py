"""Custom allauth signup forms — add a required legal-consent checkbox.

Both the email/password signup and the social (Google) signup must capture the
user's acceptance of the Terms of Service and Privacy Policy. The acceptance
timestamp is stored on the user's Customer profile (``terms_accepted_at``).
"""
from django import forms
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from allauth.account.forms import SignupForm as _AccountSignupForm
from allauth.socialaccount.forms import SignupForm as _SocialSignupForm


def _consent_label() -> str:
    terms = reverse("storefront:terms")
    privacy = reverse("storefront:privacy")
    return mark_safe(
        "I am at least 18 years old and I agree to the "
        f'<a href="{terms}" target="_blank" class="text-primary-600 font-semibold underline">Terms of Service</a> '
        "and "
        f'<a href="{privacy}" target="_blank" class="text-primary-600 font-semibold underline">Privacy Policy</a>.'
    )


class _ConsentMixin(forms.Form):
    terms_accepted = forms.BooleanField(
        required=True,
        error_messages={
            "required": "You must accept the Terms of Service and Privacy Policy to create an account.",
        },
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["terms_accepted"].label = _consent_label()

    def _record_consent(self, user):
        from apps.accounts.models import Customer

        Customer.objects.update_or_create(
            user=user,
            defaults={"terms_accepted_at": timezone.now()},
        )


class SignupForm(_ConsentMixin, _AccountSignupForm):
    def save(self, request):
        user = super().save(request)
        self._record_consent(user)
        return user


class SocialSignupForm(_ConsentMixin, _SocialSignupForm):
    def save(self, request):
        user = super().save(request)
        self._record_consent(user)
        return user
