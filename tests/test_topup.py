"""Phase 3 — Top-up (Duitku) tests.

Covers:
- initiate_topup: creates pending TopUp + calls Duitku invoice
- process_webhook_payload: success, duplicate (idempotent), invalid signature, non-success
- Bonus credit: separate BONUS ledger entry
- Webhook view: HTTP 200/400 responses
- Safety-net: recheck_topup_status credits on Duitku confirmation
- Safety-net: marks TopUp FAILED when Duitku reports failure

All Duitku network calls are replaced by MockDuitkuClient — no real credentials needed.
"""
import hashlib
import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.billing.duitku import InvoiceResult, TransactionStatus
from apps.billing.models import PaymentWebhook, TopUp
from apps.billing.services import (
    initiate_topup,
    process_webhook_payload,
    recheck_topup_status,
)
from apps.wallet.models import LedgerEntry
from tests.factories import CustomerFactory


# ── Mock Duitku client ────────────────────────────────────────────────────────

class MockDuitkuClient:
    """Stub that replaces real network calls for unit tests."""

    MERCHANT_CODE = "TESTMERCHANT"
    API_KEY = "TESTAPIKEY"

    def __init__(self, check_status_code: str = "00"):
        self.merchant_code = self.MERCHANT_CODE
        self.api_key = self.API_KEY
        self._check_status_code = check_status_code
        self.invoice_calls: list[dict] = []
        self.check_calls: list[str] = []

    def _sign(self, *parts) -> str:
        return hashlib.md5("".join(str(p) for p in parts).encode()).hexdigest()

    def create_invoice(self, merchant_order_id, amount, **kwargs) -> InvoiceResult:
        self.invoice_calls.append({"order_id": merchant_order_id, "amount": amount})
        return InvoiceResult(
            payment_url=f"https://sandbox.duitku.com/pay/{merchant_order_id}",
            va_number="88001234567890",
            reference=f"REF-{merchant_order_id}",
        )

    def check_transaction(self, merchant_order_id: str) -> TransactionStatus:
        self.check_calls.append(merchant_order_id)
        return TransactionStatus(
            status_code=self._check_status_code,
            status_message="Success" if self._check_status_code == "00" else "Pending",
            amount=0,
            reference=f"REF-{merchant_order_id}",
        )

    def verify_webhook_signature(self, merchant_code, amount, merchant_order_id, signature) -> bool:
        expected = self._sign(merchant_code, amount, merchant_order_id, self.api_key)
        return expected == signature

    def build_valid_signature(self, amount, merchant_order_id) -> str:
        return self._sign(self.merchant_code, amount, merchant_order_id, self.api_key)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_webhook_payload(client: MockDuitkuClient, merchant_order_id: str, amount: int, result_code: str = "00") -> dict:
    return {
        "merchantCode": client.MERCHANT_CODE,
        "amount": amount,
        "merchantOrderId": merchant_order_id,
        "resultCode": result_code,
        "signature": client.build_valid_signature(amount, merchant_order_id),
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def customer(db):
    return CustomerFactory()


@pytest.fixture
def mock_client():
    return MockDuitkuClient()


# ── initiate_topup ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_initiate_topup_creates_pending(customer, mock_client):
    topup, payment_url = initiate_topup(
        customer, 100_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    assert topup.status == TopUp.Status.PENDING
    assert topup.amount == 100_000
    assert topup.gateway_ref == f"REF-{topup.public_id}"
    assert topup.public_id.startswith("top_")
    assert "duitku.com" in payment_url
    assert len(mock_client.invoice_calls) == 1


@pytest.mark.django_db
def test_initiate_topup_does_not_credit_wallet(customer, mock_client):
    initiate_topup(
        customer, 50_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0


@pytest.mark.django_db
def test_initiate_topup_rejects_zero(customer, mock_client):
    with pytest.raises(ValueError):
        initiate_topup(customer, 0, callback_url="x", return_url="x", duitku_client=mock_client)


# ── Webhook: success ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_success_credits_wallet(customer, mock_client):
    topup, _ = initiate_topup(
        customer, 75_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    payload = make_webhook_payload(mock_client, topup.public_id, 75_000)
    webhook = process_webhook_payload("duitku", f"duitku:{topup.public_id}", payload, duitku_client=mock_client)

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
    topup, _ = initiate_topup(
        customer, 100_000, bonus=10_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    payload = make_webhook_payload(mock_client, topup.public_id, 100_000)
    process_webhook_payload("duitku", f"duitku:{topup.public_id}", payload, duitku_client=mock_client)

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 110_000

    entries = LedgerEntry.objects.filter(wallet=customer.wallet).order_by("created_at")
    assert entries.count() == 2
    types = {e.type for e in entries}
    assert types == {LedgerEntry.Type.TOPUP, LedgerEntry.Type.BONUS}


# ── Webhook: idempotent duplicate ─────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_duplicate_no_double_credit(customer, mock_client):
    topup, _ = initiate_topup(
        customer, 50_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    payload = make_webhook_payload(mock_client, topup.public_id, 50_000)
    idem_key = f"duitku:{topup.public_id}"

    process_webhook_payload("duitku", idem_key, payload, duitku_client=mock_client)
    process_webhook_payload("duitku", idem_key, payload, duitku_client=mock_client)

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 50_000
    assert PaymentWebhook.objects.filter(idempotency_key=idem_key).count() == 1
    assert LedgerEntry.objects.filter(wallet=customer.wallet).count() == 1


# ── Webhook: invalid signature ────────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_invalid_signature_rejected(customer, mock_client):
    topup, _ = initiate_topup(
        customer, 50_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    payload = {
        "merchantCode": mock_client.MERCHANT_CODE,
        "amount": 50_000,
        "merchantOrderId": topup.public_id,
        "resultCode": "00",
        "signature": "BADSIG000000000000000000000000",
    }
    with pytest.raises(ValueError, match="signature"):
        process_webhook_payload("duitku", f"duitku:{topup.public_id}", payload, duitku_client=mock_client)

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0
    assert not PaymentWebhook.objects.filter(idempotency_key=f"duitku:{topup.public_id}").exists()


# ── Webhook: non-success result code ─────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_non_success_no_credit(customer, mock_client):
    topup, _ = initiate_topup(
        customer, 50_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    payload = make_webhook_payload(mock_client, topup.public_id, 50_000, result_code="01")
    webhook = process_webhook_payload("duitku", f"duitku:{topup.public_id}", payload, duitku_client=mock_client)

    topup.refresh_from_db()
    assert topup.status == TopUp.Status.PENDING  # unchanged
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0
    assert webhook.processed_at is None  # not marked processed (non-success)


# ── Webhook view: HTTP responses ──────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_view_returns_200_on_success(customer, mock_client, settings):
    from unittest.mock import patch

    topup, _ = initiate_topup(
        customer, 60_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    payload = make_webhook_payload(mock_client, topup.public_id, 60_000)

    client = Client()
    with patch("apps.billing.views.process_webhook_payload") as mock_process:
        mock_process.return_value = PaymentWebhook(
            idempotency_key=f"duitku:{topup.public_id}",
            gateway="duitku",
            payload=payload,
        )
        response = client.post(
            reverse("billing:duitku_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert response.status_code == 200


@pytest.mark.django_db
def test_webhook_view_returns_400_on_invalid_signature(customer, mock_client):
    from unittest.mock import patch

    topup, _ = initiate_topup(
        customer, 60_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    payload = make_webhook_payload(mock_client, topup.public_id, 60_000)

    client = Client()
    with patch("apps.billing.views.process_webhook_payload", side_effect=ValueError("Invalid signature")):
        response = client.post(
            reverse("billing:duitku_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert response.status_code == 400


# ── Safety-net: recheck_topup_status ─────────────────────────────────────────

@pytest.mark.django_db
def test_recheck_credits_when_duitku_confirms(customer, mock_client):
    topup, _ = initiate_topup(
        customer, 80_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    assert topup.status == TopUp.Status.PENDING

    success_client = MockDuitkuClient(check_status_code="00")
    recheck_topup_status(topup, duitku_client=success_client)

    topup.refresh_from_db()
    assert topup.status == TopUp.Status.PAID
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 80_000
    assert len(success_client.check_calls) == 1


@pytest.mark.django_db
def test_recheck_marks_failed_when_duitku_reports_failure(customer, mock_client):
    topup, _ = initiate_topup(
        customer, 80_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    failed_client = MockDuitkuClient(check_status_code="01")
    recheck_topup_status(topup, duitku_client=failed_client)

    topup.refresh_from_db()
    assert topup.status == TopUp.Status.FAILED
    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 0


@pytest.mark.django_db
def test_recheck_already_paid_is_noop(customer, mock_client):
    topup, _ = initiate_topup(
        customer, 80_000,
        callback_url="https://example.com/cb",
        return_url="https://example.com/return",
        duitku_client=mock_client,
    )
    payload = make_webhook_payload(mock_client, topup.public_id, 80_000)
    process_webhook_payload("duitku", f"duitku:{topup.public_id}", payload, duitku_client=mock_client)

    success_client = MockDuitkuClient(check_status_code="00")
    recheck_topup_status(topup, duitku_client=success_client)

    # Safety-net on an already-PAID topup should not call Duitku at all.
    assert len(success_client.check_calls) == 0

    customer.wallet.refresh_from_db()
    assert customer.wallet.balance == 80_000  # unchanged — idempotent
