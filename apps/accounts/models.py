"""Accounts models: custom User (email-based), SellerProfile, Customer profile.

H1 (review): Custom User model with email as identifier — switching after data
exists is extremely painful. See CONVENTIONS.md and ADR-011.
"""
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel


class UserManager(BaseUserManager):
    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"]:
            raise ValueError("Superuser must have is_staff=True")
        if not extra_fields["is_superuser"]:
            raise ValueError("Superuser must have is_superuser=True")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user model. Email is the unique identifier — no username field.

    Allauth is configured with ACCOUNT_LOGIN_METHODS={'email'}. See ADR-011.
    """

    email = models.EmailField(unique=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self) -> str:
        return self.email

    def get_full_name(self) -> str:
        return self.email

    def get_short_name(self) -> str:
        return self.email.split("@")[0]


class SellerProfile(TimestampedModel):
    """Merchant / seller entity. Single row in single-merchant mode.

    Multi-seller ready: user FK links the owner; is_approved gates marketplace access.
    commission_rate is the platform's cut per sale (0 = no fee, single-merchant default).
    See ADR-005.
    """

    user = models.OneToOneField(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="seller_profile",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=True)
    commission_rate = models.PositiveSmallIntegerField(
        default=0, help_text="Platform commission percentage (0–100)"
    )
    bio = models.TextField(blank=True)
    logo_url = models.URLField(blank=True)
    wa_number = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "Seller Profile"

    def __str__(self) -> str:
        return self.name

    @property
    def store_url(self) -> str:
        return f"/{self.slug}/"


class Customer(TimestampedModel):
    """Extended profile for a buying user (OneToOne to custom User)."""

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="customer"
    )
    wa_number = models.CharField(max_length=20, blank=True)
    notif_wa = models.BooleanField(default=True, help_text="Receive notifications via WhatsApp")
    notif_email = models.BooleanField(default=True, help_text="Receive notifications via email")
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Customer"

    def __str__(self) -> str:
        return self.user.email