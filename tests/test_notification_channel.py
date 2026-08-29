"""ADR-022 — notification channel choice, WA number validation, kirim.chat backend."""
import json
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import NotificationChannel
from apps.core.validators import normalize_wa_number, validate_wa_number
from apps.notifications.whatsapp import KirimChatBackend
from tests.factories import CustomerFactory


# ── Validator / normalization ────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("081234567890", "6281234567890"),
    ("+62 812-3456-7890", "6281234567890"),
    ("6281234567890", "6281234567890"),
    ("", ""),
])
def test_normalize_wa_number(raw, expected):
    assert normalize_wa_number(raw) == expected


def test_validate_wa_number_accepts_blank_and_valid():
    validate_wa_number("")
    validate_wa_number("081234567890")


@pytest.mark.parametrize("bad", ["123", "62812", "081-not-a-number-xx", "62" + "9" * 20])
def test_validate_wa_number_rejects_garbage(bad):
    with pytest.raises(ValidationError):
        validate_wa_number(bad)


# ── resolve_channel() ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_resolve_channel_defaults_to_email():
    c = CustomerFactory()
    assert c.resolve_channel() == NotificationChannel.EMAIL


@pytest.mark.django_db
def test_resolve_channel_wa_requires_verified_number():
    c = CustomerFactory()
    c.wa_number = "6281234567890"
    c.notification_channel = NotificationChannel.WHATSAPP
    c.save()

    # chosen but not verified -> falls back to email
    assert not c.wa_verified
    assert c.resolve_channel() == NotificationChannel.EMAIL

    c.wa_number_verified_at = timezone.now()
    c.save()
    assert c.resolve_channel() == NotificationChannel.WHATSAPP


@pytest.mark.django_db
def test_resolve_channel_wa_without_number_falls_back():
    c = CustomerFactory()
    c.notification_channel = NotificationChannel.WHATSAPP
    c.wa_number_verified_at = timezone.now()  # verified flag but no number
    c.save()
    assert c.resolve_channel() == NotificationChannel.EMAIL


# ── KirimChatBackend ─────────────────────────────────────────────────────────

def test_kirimchat_backend_noop_without_token(monkeypatch, caplog):
    monkeypatch.delenv("WA_TOKEN", raising=False)
    with patch("urllib.request.urlopen") as urlopen:
        KirimChatBackend().send("6281234567890", "hi")
    urlopen.assert_not_called()


def test_kirimchat_backend_posts_expected_payload(monkeypatch):
    monkeypatch.setenv("WA_TOKEN", "kc_live_test")
    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"success": true}'

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        captured["body"] = json.loads(req.data)
        return _Resp()

    with patch("urllib.request.urlopen", _fake_urlopen):
        KirimChatBackend().send("6281234567890", "Halo")

    assert captured["url"].endswith("/messages/send")
    assert captured["headers"]["authorization"] == "Bearer kc_live_test"
    assert captured["body"] == {
        "phone_number": "6281234567890",
        "channel": "whatsapp",
        "message_type": "text",
        "content": "Halo",
    }
