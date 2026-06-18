"""Duitku payment gateway client.

Credentials are read (in priority order) from:
  1. Setting model keys: DUITKU_MERCHANT_CODE, DUITKU_API_KEY, DUITKU_SANDBOX
  2. Django settings attributes of the same names

Endpoints:
  Sandbox:    https://sandbox.duitku.com/webapi
  Production: https://passport.duitku.com/webapi

Webhook signature (from Duitku docs):
  MD5(merchantCode + amount + merchantOrderId + apiKey)
"""
import hashlib
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SANDBOX_URL = "https://sandbox.duitku.com/webapi"
PRODUCTION_URL = "https://passport.duitku.com/webapi"


class DuitkuError(Exception):
    """Raised when Duitku returns an error or the network call fails."""


@dataclass
class InvoiceResult:
    payment_url: str
    va_number: str
    reference: str
    raw: dict = field(default_factory=dict)


@dataclass
class TransactionStatus:
    status_code: str   # "00" = success, "01" = failed, others = pending
    status_message: str
    amount: int
    reference: str
    raw: dict = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status_code == "00"

    @property
    def is_failed(self) -> bool:
        return self.status_code == "01"

    @property
    def is_pending(self) -> bool:
        return not self.is_success and not self.is_failed


class DuitkuClient:
    def __init__(self, merchant_code: str, api_key: str, base_url: str = SANDBOX_URL):
        self.merchant_code = merchant_code
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_settings(cls) -> "DuitkuClient":
        """Instantiate from Setting model / env. Raises DuitkuError if unconfigured.

        Security (H1):
          DUITKU_MERCHANT_CODE — non-sensitive; readable from Setting model OR env.
          DUITKU_API_KEY       — secret; read from env ONLY (os.environ / Django settings
                                 attr which itself comes from .env). Never from Setting/DB
                                 to prevent leakage via DB backups or Admin.
          DUITKU_SANDBOX       — flag; readable from Setting model OR env.
        """
        import os

        from django.conf import settings as django_settings

        from apps.core.models import Setting

        # Non-sensitive: Setting model → env fallback
        merchant_code = Setting.get("DUITKU_MERCHANT_CODE") or getattr(
            django_settings, "DUITKU_MERCHANT_CODE", ""
        ) or os.environ.get("DUITKU_MERCHANT_CODE", "")

        # Secret: env ONLY — never Setting/DB
        api_key = os.environ.get("DUITKU_API_KEY", "") or getattr(
            django_settings, "DUITKU_API_KEY", ""
        )

        sandbox_raw = Setting.get("DUITKU_SANDBOX", "true") or os.environ.get(
            "DUITKU_SANDBOX", "true"
        )
        sandbox = sandbox_raw.strip().lower() != "false"
        base_url = SANDBOX_URL if sandbox else PRODUCTION_URL

        if not merchant_code or not api_key:
            raise DuitkuError(
                "Duitku credentials not configured. "
                "DUITKU_MERCHANT_CODE: Setting model or env. "
                "DUITKU_API_KEY: env only (never DB)."
            )
        return cls(merchant_code=merchant_code, api_key=api_key, base_url=base_url)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _sign(self, *parts: str | int) -> str:
        return hashlib.md5("".join(str(p) for p in parts).encode()).hexdigest()

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise DuitkuError(f"Duitku HTTP {exc.code} at {path}: {body}") from exc
        except Exception as exc:
            raise DuitkuError(f"Duitku request failed at {path}: {exc}") from exc

    # ── Public API ────────────────────────────────────────────────────────────

    def create_invoice(
        self,
        merchant_order_id: str,
        amount: int,
        product_details: str,
        email: str,
        callback_url: str,
        return_url: str,
        expiry_period: int = 1440,
    ) -> InvoiceResult:
        """Request a payment invoice from Duitku. Returns payment URL + reference."""
        signature = self._sign(self.merchant_code, amount, merchant_order_id, self.api_key)
        payload = {
            "merchantCode": self.merchant_code,
            "paymentAmount": amount,
            "merchantOrderId": merchant_order_id,
            "productDetails": product_details,
            "email": email,
            "callbackUrl": callback_url,
            "returnUrl": return_url,
            "signature": signature,
            "expiryPeriod": expiry_period,
        }
        result = self._post("/api/merchant/v2/inquiry", payload)
        if result.get("statusCode") != "00":
            raise DuitkuError(
                f"Duitku invoice creation failed (statusCode={result.get('statusCode')}): {result}"
            )
        return InvoiceResult(
            payment_url=result.get("paymentUrl", ""),
            va_number=result.get("vaNumber", ""),
            reference=result.get("reference", ""),
            raw=result,
        )

    def check_transaction(self, merchant_order_id: str) -> TransactionStatus:
        """Query Duitku for the current status of a transaction."""
        signature = self._sign(self.merchant_code, merchant_order_id, self.api_key)
        payload = {
            "merchantCode": self.merchant_code,
            "merchantOrderId": merchant_order_id,
            "signature": signature,
        }
        result = self._post("/api/merchant/transactionStatus", payload)
        return TransactionStatus(
            status_code=result.get("statusCode", ""),
            status_message=result.get("statusMessage", ""),
            amount=int(result.get("amount", 0)),
            reference=result.get("reference", ""),
            raw=result,
        )

    def verify_webhook_signature(
        self,
        merchant_code: str,
        amount: int,
        merchant_order_id: str,
        signature: str,
    ) -> bool:
        """Return True if the webhook payload signature is valid."""
        expected = self._sign(merchant_code, amount, merchant_order_id, self.api_key)
        return expected == signature

    def build_webhook_signature(self, merchant_order_id: str, amount: int) -> str:
        """Build the expected signature for a known order (used by safety-net polling)."""
        return self._sign(self.merchant_code, amount, merchant_order_id, self.api_key)
