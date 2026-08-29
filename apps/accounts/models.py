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

from apps.core.models import NotificationChannel, TimestampedModel
from apps.core.validators import validate_wa_number


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

    class Plan(models.TextChoices):
        FREE = "free", "Free"
        PRO = "pro", "PRO"

    class OnboardingStep(models.TextChoices):
        IDENTITY = "identity", "Store identity"
        PRODUCT = "product", "First product"
        PUBLISH = "publish", "Publish"

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
    onboarding_completed = models.BooleanField(
        default=True,
        help_text="False forces the seller through the guided store-setup wizard "
        "(apply() sets this to False for every newly-created SellerProfile).",
    )

    onboarding_step = models.CharField(
        max_length=20, choices=OnboardingStep.choices, default=OnboardingStep.IDENTITY,
        help_text="Where a not-yet-onboarded seller resumes the setup wizard.",
    )
    commission_rate = models.PositiveSmallIntegerField(
        default=0, help_text="Platform commission percentage (0–100)"
    )
    bio = models.TextField(blank=True)
    logo = models.ImageField(upload_to="seller/logo/", blank=True, null=True)
    wa_number = models.CharField(max_length=20, blank=True)

    # Seller plan & KYC
    plan = models.CharField(max_length=10, choices=Plan.choices, default=Plan.FREE)
    kyc_verified = models.BooleanField(default=False)

    # Payout bank details (required before withdrawal can be approved)
    payout_bank_name = models.CharField(max_length=100, blank=True)
    payout_account_number = models.CharField(max_length=50, blank=True)
    payout_account_name = models.CharField(max_length=200, blank=True)

    # Custom domain + tracking pixels
    custom_domain = models.CharField(max_length=253, blank=True, help_text="e.g. shop.example.com")
    ga_tracking_id = models.CharField(max_length=30, blank=True, help_text="e.g. G-XXXXXXXXXX")
    fb_pixel_id = models.CharField(max_length=20, blank=True)

    # Static QRIS — buyer pays the seller's own static QRIS directly (money never
    # touches the platform wallet or Duitku). Orders wait for the seller to
    # manually confirm receipt before provisioning runs. See ADR / checkout.py.
    qris_enabled = models.BooleanField(default=False)
    qris_image = models.ImageField(upload_to="qris/", blank=True, null=True)
    qris_instructions = models.TextField(
        blank=True,
        help_text="Shown to the buyer on the payment screen — e.g. transfer the exact "
                  "amount, then upload your receipt.",
    )

    class Meta:
        verbose_name = "Seller Profile"

    def __str__(self) -> str:
        return self.name

    @property
    def qris_ready(self) -> bool:
        """True when this seller can actually accept Static QRIS payments."""
        return bool(self.qris_enabled and self.qris_image)

    @property
    def store_url(self) -> str:
        return f"/{self.slug}/"


class Customer(TimestampedModel):
    """Extended profile for a buying user (OneToOne to custom User).

    Notification delivery is a *single channel choice* (ADR-022): the customer
    receives each notification via email OR WhatsApp, never both. WhatsApp is
    only usable once the number is verified by OTP. Value documents
    (receipts / invoices / license keys) are always emailed regardless — that
    rule lives in the notification handlers, not here.
    """

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="customer"
    )
    wa_number = models.CharField(
        max_length=20, blank=True, validators=[validate_wa_number]
    )
    wa_number_verified_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Set when the number passes OTP verification; cleared when the number changes.",
    )
    notification_channel = models.CharField(
        max_length=10,
        choices=NotificationChannel.choices,
        default=NotificationChannel.EMAIL,
        help_text="Preferred channel. WhatsApp only takes effect once the number is verified.",
    )
    notif_promo = models.BooleanField(
        default=False,
        help_text="Explicit opt-in for promotional messages (separate from transactional).",
    )
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Customer"

    def __str__(self) -> str:
        return self.user.email

    @property
    def wa_verified(self) -> bool:
        return self.wa_number_verified_at is not None

    def resolve_channel(self) -> str:
        """The channel a notification will actually go out on.

        Falls back to email whenever WhatsApp is chosen but not usable
        (no number, or number not verified).
        """
        if (
            self.notification_channel == NotificationChannel.WHATSAPP
            and self.wa_number
            and self.wa_verified
        ):
            return NotificationChannel.WHATSAPP
        return NotificationChannel.EMAIL

    @property
    def notify_email_address(self) -> str:
        return self.user.email