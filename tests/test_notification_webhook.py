"""kirim.chat webhook: signature, delivery status, failed→email fallback, STOP."""
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import NotificationChannel
from apps.notifications.models import NotificationDelivery, WhatsAppSuppression
from tests.factories import CustomerFactory

SECRET = "whsec_test_secret"


def _post(client, payload: dict, *, secret=SECRET, sign=True):
    raw = json.dumps(payload).encode()
    headers = {}
    if sign:
        digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        headers["HTTP_X_KIRIMCHAT_SIGNATURE"] = f"sha256={digest}"
    return client.post(
        reverse("notifications:kirimchat_webhook"),
        data=raw, content_type="application/json", **headers,
    )


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("KIRIMCHAT_WEBHOOK_SECRET", SECRET)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Idempotency keys live in the (shared) cache — isolate each test."""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_rejects_bad_signature(client):
    resp = client.post(
        reverse("notifications:kirimchat_webhook"),
        data=b'{"event_type":"message.sent","data":{}}',
        content_type="application/json",
        HTTP_X_KIRIMCHAT_SIGNATURE="sha256=deadbeef",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_delivered_updates_delivery(client):
    d = NotificationDelivery.objects.create(
        channel="whatsapp", recipient="628111", event="x",
        status=NotificationDelivery.Status.SENT, provider_msg_id="msg_1",
    )
    resp = _post(client, {
        "event_type": "message.delivered", "event_id": "e1",
        "data": {"message_id": "msg_1"},
    })
    assert resp.status_code == 200
    d.refresh_from_db()
    assert d.status == NotificationDelivery.Status.DELIVERED


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_email")
def test_failed_triggers_email_fallback(mock_email, client):
    cust = CustomerFactory()
    d = NotificationDelivery.objects.create(
        customer=cust, channel="whatsapp", recipient="628111", event="subscription.suspended",
        status=NotificationDelivery.Status.SENT, provider_msg_id="msg_2",
        email_subject="Access suspended", email_body="body text",
    )
    resp = _post(client, {
        "event_type": "message.failed", "event_id": "e2",
        "data": {"message_id": "msg_2", "reason": "undeliverable"},
    })
    assert resp.status_code == 200
    d.refresh_from_db()
    assert d.status == NotificationDelivery.Status.FALLBACK_SENT
    mock_email.delay.assert_called_once_with(cust.user.email, "Access suspended", "body text")


@pytest.mark.django_db
def test_idempotent_on_event_id(client):
    d = NotificationDelivery.objects.create(
        channel="whatsapp", recipient="628111", event="x",
        status=NotificationDelivery.Status.SENT, provider_msg_id="msg_3",
    )
    body = {"event_type": "message.read", "event_id": "dup", "data": {"message_id": "msg_3"}}
    assert _post(client, body).status_code == 200
    d.refresh_from_db()
    assert d.status == NotificationDelivery.Status.READ
    # second delivery of same event_id is a no-op
    resp = _post(client, body)
    assert b"duplicate" in resp.content


@pytest.mark.django_db
@patch("apps.notifications.tasks.deliver_whatsapp")
def test_inbound_stop_suppresses_and_switches_channel(mock_wa, client):
    cust = CustomerFactory()
    cust.wa_number = "6281234567890"
    cust.wa_number_verified_at = timezone.now()
    cust.notification_channel = NotificationChannel.WHATSAPP
    cust.save()

    resp = _post(client, {
        "event_type": "message.received", "event_id": "e4",
        "data": {"customer_phone": "6281234567890", "content": "STOP", "direction": "inbound"},
    })
    assert resp.status_code == 200
    assert WhatsAppSuppression.objects.filter(number="6281234567890").exists()
    cust.refresh_from_db()
    assert cust.notification_channel == NotificationChannel.EMAIL
    mock_wa.delay.assert_called_once()  # opt-out confirmation


@pytest.mark.django_db
def test_missing_secret_returns_500(client, monkeypatch):
    monkeypatch.delenv("KIRIMCHAT_WEBHOOK_SECRET", raising=False)
    resp = _post(client, {"event_type": "message.sent", "data": {}}, sign=False)
    assert resp.status_code == 500
