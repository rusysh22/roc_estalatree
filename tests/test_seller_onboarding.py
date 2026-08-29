"""Tests for the seller apply -> onboarding flow (docs/feedback, sections F & G).

Coverage:
  1. Anonymous apply -> redirected to login.
  2. Unverified email -> apply POST rejected, no SellerProfile created.
  3. Verified email -> apply POST instantly approves + starts onboarding (no manual review).
  4. seller_required views redirect to onboarding while onboarding_completed=False.
  5. Full onboarding wizard: identity -> product -> publish -> seller:home reachable.
"""
import pytest
from allauth.account.models import EmailAddress
from django.test import Client
from django.urls import reverse

from apps.accounts.models import SellerProfile
from apps.storefront.models import StorePage
from tests.factories import UserFactory


@pytest.fixture
def unverified_user(db):
    user = UserFactory()
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=False)
    return user


@pytest.fixture
def verified_user(db):
    user = UserFactory()
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
    return user


@pytest.mark.django_db
def test_apply_anonymous_redirects_to_login():
    resp = Client().get(reverse("seller:apply"))
    assert resp.status_code == 302
    assert "login" in resp["Location"]


@pytest.mark.django_db
def test_apply_post_unverified_email_creates_nothing(unverified_user):
    client = Client()
    client.force_login(unverified_user)
    resp = client.post(reverse("seller:apply"), {"store_name": "My Store"})
    assert resp.status_code == 302
    assert not SellerProfile.objects.filter(user=unverified_user).exists()


@pytest.mark.django_db
def test_apply_post_verified_email_instantly_approved(verified_user):
    client = Client()
    client.force_login(verified_user)
    resp = client.post(reverse("seller:apply"), {"store_name": "My Great Store"})
    assert resp.status_code == 302
    assert resp["Location"] == reverse("seller:onboarding")

    seller = SellerProfile.objects.get(user=verified_user)
    assert seller.is_approved is True
    assert seller.onboarding_completed is False
    assert seller.onboarding_step == SellerProfile.OnboardingStep.IDENTITY


@pytest.mark.django_db
def test_seller_required_view_redirects_to_onboarding_when_incomplete(verified_user):
    client = Client()
    client.force_login(verified_user)
    client.post(reverse("seller:apply"), {"store_name": "Incomplete Store"})

    resp = client.get(reverse("seller:home"))
    assert resp.status_code == 302
    assert resp["Location"] == reverse("seller:onboarding")


@pytest.mark.django_db
def test_full_onboarding_wizard_reaches_dashboard(verified_user):
    client = Client()
    client.force_login(verified_user)
    client.post(reverse("seller:apply"), {"store_name": "Wizard Store"})
    seller = SellerProfile.objects.get(user=verified_user)

    # Step 1: identity
    resp = client.post(reverse("seller:onboarding"), {
        "title": "Wizard Store", "description": "",
    })
    assert resp.status_code == 302
    seller.refresh_from_db()
    assert seller.onboarding_step == SellerProfile.OnboardingStep.PRODUCT

    # Step 2: first product
    resp = client.post(reverse("seller:onboarding"), {
        "product_name": "My First Product", "price": "75000",
    })
    assert resp.status_code == 302
    seller.refresh_from_db()
    assert seller.onboarding_step == SellerProfile.OnboardingStep.PUBLISH

    store_page = StorePage.objects.get(slug=seller.slug)
    assert store_page.blocks.count() == 1
    assert store_page.blocks.first().product.name == "My First Product"
    assert store_page.blocks.first().product.plans.first().price == 75000

    # Step 3: publish
    resp = client.post(reverse("seller:onboarding"), {})
    assert resp.status_code == 302
    assert resp["Location"] == reverse("seller:home")
    seller.refresh_from_db()
    store_page.refresh_from_db()
    assert seller.onboarding_completed is True
    assert store_page.is_published is True

    # Now seller:home (and other seller_required views) work without redirect
    resp = client.get(reverse("seller:home"))
    assert resp.status_code == 200
