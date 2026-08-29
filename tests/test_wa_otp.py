"""WhatsApp number OTP verification (ADR-022, N.4)."""
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.notifications import otp
from apps.notifications.models import WhatsAppOTP
from tests.factories import CustomerFactory


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import caches

    def _clear():
        for alias in ("default", "rate_limit"):
            try:
                caches[alias].clear()
            except Exception:
                pass

    _clear()
    yield
    _clear()


def _last_code(mock_wa):
    # message text is "Your berlanggan verification code is 123456. ..."
    text = mock_wa.delay.call_args[0][1]
    return "".join(c for c in text.split("code is ")[1][:6] if c.isdigit())


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
def test_request_and_verify_happy_path(mock_wa):
    c = CustomerFactory()
    otp.request_code(c, "081234567890")

    mock_wa.delay.assert_called_once()
    assert mock_wa.delay.call_args[0][0] == "6281234567890"
    code = _last_code(mock_wa)

    otp.verify_code(c, "6281234567890", code)
    c.refresh_from_db()
    assert c.wa_number == "6281234567890"
    assert c.wa_verified


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
def test_wrong_code_counts_attempts_then_locks(mock_wa):
    c = CustomerFactory()
    otp.request_code(c, "081234567890")

    for _ in range(WhatsAppOTP.MAX_ATTEMPTS):
        with pytest.raises(otp.OtpError, match="Incorrect"):
            otp.verify_code(c, "6281234567890", "000000")

    with pytest.raises(otp.OtpError, match="Too many"):
        otp.verify_code(c, "6281234567890", "000000")
    c.refresh_from_db()
    assert not c.wa_verified


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
def test_expired_code_rejected(mock_wa):
    c = CustomerFactory()
    otp.request_code(c, "081234567890")
    WhatsAppOTP.objects.filter(customer=c).update(
        expires_at=timezone.now() - timezone.timedelta(seconds=1)
    )
    with pytest.raises(otp.OtpError, match="expired"):
        otp.verify_code(c, "6281234567890", _last_code(mock_wa))


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
def test_send_cooldown(mock_wa):
    c = CustomerFactory()
    otp.request_code(c, "081234567890")
    with pytest.raises(otp.OtpError, match="wait a minute"):
        otp.request_code(c, "081234567890")


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
def test_suppressed_number_cannot_request(mock_wa):
    from apps.notifications.models import WhatsAppSuppression
    WhatsAppSuppression.objects.create(number="6281234567890", reason="opt_out")
    c = CustomerFactory()
    with pytest.raises(otp.OtpError, match="opted out"):
        otp.request_code(c, "081234567890")


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
def test_views_wire_up(mock_wa, client, django_user_model):
    user = django_user_model.objects.create_user(email="o@x.com", password="pw12345678")
    c = CustomerFactory(user=user)
    client.force_login(user)

    r1 = client.post(reverse("dashboard:wa_send_otp"), {"wa_number": "081234567890"})
    assert r1.status_code == 302
    code = _last_code(mock_wa)

    r2 = client.post(reverse("dashboard:wa_verify_otp"),
                     {"wa_number": "6281234567890", "code": code})
    assert r2.status_code == 302
    c.refresh_from_db()
    assert c.wa_verified
