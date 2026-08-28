"""Top-up (Sumopod) tests.

Covers:
- initiate_topup: creates pending TopUp + calls Sumopod create_payment
- process_webhook_payload: completed, duplicate (idempotent), failed/expired, test, amount mismatch
- Bonus credit: separate BONUS ledger entry
- Webhook view: HTTP 200 / 401 responses
- Safety-net: recheck_topup_status expires stale pending TopUps

All Sumopod network calls are replaced by MockSumopodClient — no real credentials needed.
"""
import json
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import PaymentWebhook, TopUp
from apps.billing.services import (
    initiate_topup,
    process_webhook_payload,
    recheck_topup_status,
)
from apps.billing.sumopod import PaymentResult
from apps.wallet.models import LedgerEntry
from tests.factories import CustomerFactory


# ── Mock Sumopod client ──────────────────────────────────────────────────────

class MockSumopodClient:
    """Stub that replaces real network calls for unit tests."""

    def __init__(self, *, webhook_ok: bool = True):
        self._webhook_ok = webhook_ok
        self.payment_calls: list[dict] = []

    def create_payment(self, order_id, amount, **kwargs) -> PaymentResult:
        self.payment_calls.append({"order_id": order_id, "amount": amount})
        return PaymentResult(
            payment_url=f"https://pay.sumopod.com/pay/{order_id}",
            payment_id=f"pay_{order_id}",
            payment_code="1308300301295957",
            status="pending",
        )

    def verify_webhook(self, headers, raw_body) -> bool:
        return self._webhook_ok

    def check_status(self, order_id):
        from apps.billing.sumopod import SumopodError
        raise SumopodError("no status endpoint")


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_webhook_payload(order_id: str, amount: int, event_type: str = "payment.completed") -> dict:
    return {
        "event_type": event_type,
        "data": {
            "payment_id": f"pay_{order_id}",
            "order_id": order_id,
            "amount": amount,
            "fee": 750,
            "net_amount": amount,
            "status": event_type.split(".", 1)[1],
            "payment_method": "qris",
        },
    }


def _topup(customer, amount, mock_client, *, bonus: int = 0):
    return initiate_topup(
        customer, amount,
        bonus=bonus,
        return_url="https://example.com/return",
        gateway_client=mock_client,
    )


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def customer(db):
    return CustomerFactory()


@pytest.fixture
def mock_client():
    return MockSumopodClient()


# ── initiate_topup ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_initiate_topup_creates_pending(customer, mock_client):
    topup, payment_url = _topup(customer, 100_000, mock_client)
    assert topup.status == TopUp.Status.PENDING
    assert topup.amount == 100_000
    assert topup.gateway == TopUp.Gateway.SUMOPOD
    assert topup.gateway_ref == f"pay_{topup.public_id}"
    assert topup.public_id.startswith("top_")
    assert "sumopod.com" in payment_url
    assert len(mock_client.payment_calls) == 1


@pytest.mark.django_db
def test_initiate_topup_does_not_credit_wallet(customer, mock_client):
    _topup(customer, 50_000, mock_client)
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0


@pytest.mark.django_db
def test_initiate_topup_rejects_zero(customer, mock_client):
    with pytest.raises(ValueError):
        _topup(customer, 0, mock_client)


# ── Webhook: completed ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_completed_credits_wallet(customer, mock_client):
    topup, _ = _topup(customer, 75_000, mock_client)
    payload = make_webhook_payload(topup.public_id, 75_000)
    webhook = process_webhook_payload("sumopod", f"sumopod:{topup.public_id}", payload)

    topup.refresh_from_db()
    assert topup.status == TopUp.Status.PAID
    assert topup.ledger_entry is not None

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 75_000

    assert webhook.processed_at is not None
    entries = LedgerEntry.objects.filter(wallet=customer.wallet)
    assert entries.count() == 1
    assert entries.first().type == LedgerEntry.Type.TOPUP


@pytest.mark.django_db
def test_webhook_with_bonus_creates_two_entries(customer, mock_client):
    topup, _ = _topup(customer, 100_000, mock_client, bonus=10_000)
    payload = make_webhook_payload(topup.public_id, 100_000)
    process_webhook_payload("sumopod", f"sumopod:{topup.public_id}", payload)

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 110_000

    entries = LedgerEntry.objects.filter(wallet=customer.wallet).order_by("created_at")
    assert entries.count() == 2
    assert {e.type for e in entries} == {LedgerEntry.Type.TOPUP, LedgerEntry.Type.BONUS}


# ── Webhook: idempotent duplicate ────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_duplicate_no_double_credit(customer, mock_client):
    topup, _ = _topup(customer, 50_000, mock_client)
    payload = make_webhook_payload(topup.public_id, 50_000)
    idem_key = f"sumopod:msg_{topup.public_id}"

    process_webhook_payload("sumopod", idem_key, payload)
    process_webhook_payload("sumopod", idem_key, payload)

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 50_000
    assert PaymentWebhook.objects.filter(idempotency_key=idem_key).count() == 1
    assert LedgerEntry.objects.filter(wallet=customer.wallet).count() == 1


# ── Webhook: failed / expired ────────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_failed_marks_failed(customer, mock_client):
    topup, _ = _topup(customer, 50_000, mock_client)
    payload = make_webhook_payload(topup.public_id, 50_000, event_type="payment.failed")
    webhook = process_webhook_payload("sumopod", f"sumopod:{topup.public_id}:f", payload)

    topup.refresh_from_db()
    assert topup.status == TopUp.Status.FAILED
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0
    assert webhook.processed_at is not None


@pytest.mark.django_db
def test_webhook_expired_marks_expired(customer, mock_client):
    topup, _ = _topup(customer, 50_000, mock_client)
    payload = make_webhook_payload(topup.public_id, 50_000, event_type="payment.expired")
    process_webhook_payload("sumopod", f"sumopod:{topup.public_id}:e", payload)

    topup.refresh_from_db()
    assert topup.status == TopUp.Status.EXPIRED


@pytest.mark.django_db
def test_webhook_test_event_is_noop(customer, mock_client):
    payload = {"event_type": "payment.test", "data": {}}
    webhook = process_webhook_payload("sumopod", "sumopod:test-1", payload)
    assert webhook.processed_at is not None
    assert TopUp.objects.count() == 0


# ── Webhook: order not found ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_unknown_order_raises(customer, mock_client):
    from apps.billing.services import TopUpNotFoundError

    payload = make_webhook_payload("top_doesnotexist", 50_000)
    with pytest.raises(TopUpNotFoundError):
        process_webhook_payload("sumopod", "sumopod:missing-1", payload)


# ── Webhook view: HTTP responses ─────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_view_returns_200_end_to_end(customer, mock_client):
    from unittest.mock import patch

    topup, _ = _topup(customer, 60_000, mock_client)
    payload = make_webhook_payload(topup.public_id, 60_000)

    client = Client()
    with patch("apps.billing.sumopod.SumopodClient.from_settings", return_value=mock_client):
        response = client.post(
            reverse("billing:sumopod_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            **{"HTTP_SVIX_ID": f"msg_{topup.public_id}"},
        )
    assert response.status_code == 200
    topup.refresh_from_db()
    assert topup.status == TopUp.Status.PAID


@pytest.mark.django_db
def test_webhook_view_returns_401_on_bad_signature(customer):
    from unittest.mock import patch

    bad_client = MockSumopodClient(webhook_ok=False)
    payload = make_webhook_payload("top_whatever", 60_000)

    client = Client()
    with patch("apps.billing.sumopod.SumopodClient.from_settings", return_value=bad_client):
        response = client.post(
            reverse("billing:sumopod_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert response.status_code == 401


# ── M1: amount mismatch ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_amount_mismatch_not_credited(customer, mock_client):
    topup, _ = _topup(customer, 100_000, mock_client)
    payload = make_webhook_payload(topup.public_id, 50_000)  # wrong amount
    webhook = process_webhook_payload("sumopod", f"sumopod:{topup.public_id}", payload)

    topup.refresh_from_db()
    assert topup.status == TopUp.Status.PENDING
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0
    assert webhook.processed_at is None


# ── Safety-net: expiry ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_recheck_marks_expired_after_window(customer, mock_client):
    from apps.billing.services import TOPUP_EXPIRY_MINUTES

    topup, _ = _topup(customer, 50_000, mock_client)

    past = timezone.now() - timedelta(minutes=TOPUP_EXPIRY_MINUTES + 1)
    TopUp.objects.filter(pk=topup.pk).update(created_at=past)
    topup.refresh_from_db()

    recheck_topup_status(topup)

    topup.refresh_from_db()
    assert topup.status == TopUp.Status.EXPIRED
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0


@pytest.mark.django_db
def test_recheck_within_window_is_noop(customer, mock_client):
    topup, _ = _topup(customer, 50_000, mock_client)
    recheck_topup_status(topup)
    topup.refresh_from_db()
    assert topup.status == TopUp.Status.PENDING


# ── Fee passthrough ──────────────────────────────────────────────────────────

def test_estimate_fee_matches_sumopod_formula():
    from apps.billing.sumopod import estimate_fee
    assert estimate_fee(15_000) == 405   # 0.7% + 300, matches live sandbox response
    assert estimate_fee(25_000) == 475


@pytest.mark.django_db
def test_webhook_credits_full_amount_when_customer_paid_fee(customer, mock_client):
    """Fee passthrough: webhook `amount` is gross (amount+fee), `net_amount` is what
    we asked for. Wallet is still credited the full requested amount."""
    topup, _ = _topup(customer, 50_000, mock_client)
    payload = {
        "event_type": "payment.completed",
        "data": {"payment_id": "pay_x", "order_id": topup.public_id,
                 "amount": 50_650, "fee": 650, "net_amount": 50_000},
    }
    process_webhook_payload("sumopod", f"sumopod:{topup.public_id}", payload)
    topup.refresh_from_db(); customer.wallet.refresh_from_db()
    assert topup.status == TopUp.Status.PAID
    assert customer.wallet.balance == 50_000
