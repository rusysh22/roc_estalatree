"""WhatsApp number verification via OTP (ADR-022, N.4).

Flow:
  request_code(customer, number) -> sends a 6-digit code by WhatsApp
  verify_code(customer, number, code) -> marks Customer.wa_number_verified_at

Rate limits (per number):
  - 60s cooldown between sends
  - max 3 sends per rolling hour
  - max WhatsAppOTP.MAX_ATTEMPTS guesses per code
"""
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

CODE_TTL = 60 * 5           # seconds a code stays valid
SEND_COOLDOWN = 60          # seconds between sends to one number
MAX_SENDS_PER_HOUR = 3

_RL_WINDOW = 60 * 60


class OtpError(Exception):
    """User-facing verification error (safe to show)."""


def _rl_cache():
    from django.core.cache import cache, caches
    return caches["rate_limit"] if "rate_limit" in caches else cache


def _norm(number: str) -> str:
    from apps.notifications.whatsapp import normalize_number
    return normalize_number(number)


def request_code(customer, number: str) -> None:
    from apps.notifications.models import WhatsAppOTP
    from apps.notifications.tasks import deliver_whatsapp

    number = _norm(number)
    if not number:
        raise OtpError("Enter a WhatsApp number first.")

    from apps.core.validators import validate_wa_number
    from django.core.exceptions import ValidationError as DjangoValidationError
    try:
        validate_wa_number(number)
    except DjangoValidationError:
        raise OtpError("That doesn't look like a valid WhatsApp number.")

    from apps.notifications.whatsapp import wa_suppressed
    if wa_suppressed(number):
        raise OtpError("This number has opted out of WhatsApp messages. Reply START on WhatsApp first.")

    cache = _rl_cache()
    cd_key = f"waotp:cd:{number}"
    if cache.get(cd_key):
        raise OtpError("Please wait a minute before requesting another code.")

    cnt_key = f"waotp:cnt:{number}"
    cache.add(cnt_key, 0, _RL_WINDOW)
    try:
        sends = cache.incr(cnt_key)
    except ValueError:
        cache.set(cnt_key, 1, _RL_WINDOW)
        sends = 1
    if sends > MAX_SENDS_PER_HOUR:
        raise OtpError("Too many codes requested. Try again later.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    WhatsAppOTP.objects.create(
        customer=customer,
        number=number,
        code_hash=make_password(code),
        expires_at=timezone.now() + timezone.timedelta(seconds=CODE_TTL),
    )
    cache.set(cd_key, 1, SEND_COOLDOWN)

    deliver_whatsapp.delay(
        number,
        f"Your berlanggan verification code is {code}. It expires in 5 minutes. "
        f"Do not share this code with anyone.",
    )


def verify_code(customer, number: str, code: str) -> None:
    from apps.notifications.models import WhatsAppOTP

    number = _norm(number)
    code = (code or "").strip()
    otp = (
        WhatsAppOTP.objects.filter(customer=customer, number=number, consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if otp is None:
        raise OtpError("Request a code first.")
    if timezone.now() >= otp.expires_at:
        raise OtpError("That code has expired. Request a new one.")
    if otp.attempts >= WhatsAppOTP.MAX_ATTEMPTS:
        raise OtpError("Too many incorrect attempts. Request a new code.")

    otp.attempts += 1
    if not check_password(code, otp.code_hash):
        otp.save(update_fields=["attempts", "updated_at"])
        raise OtpError("Incorrect code.")

    otp.consumed_at = timezone.now()
    otp.save(update_fields=["attempts", "consumed_at", "updated_at"])

    if customer.wa_number != number:
        customer.wa_number = number
    customer.wa_number_verified_at = timezone.now()
    customer.save(update_fields=["wa_number", "wa_number_verified_at", "updated_at"])
