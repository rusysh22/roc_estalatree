"""Sumopod payment gateway client.

Replaces the former Duitku integration (see docs/DECISIONS.md).

Credentials are read from:
  SUMOPOD_API_KEY        — secret; env ONLY (os.environ / Django settings attr).
                           Never from the Setting model / DB (leak via backups/Admin).
  SUMOPOD_WEBHOOK_SECRET  — secret (whsec_...); env ONLY. Svix signing secret.
  SUMOPOD_WEBHOOK_TOKEN   — secret (whtok_...); env ONLY. Simple shared token.
  SUMOPOD_SANDBOX         — flag; Setting model OR env.

Endpoints:
  Sandbox:    https://api-pay-sandbox.sumopod.com
  Production: https://api-pay.sumopod.com

Payment creation:
  POST /api/v1/payments   (header: X-Api-Key)

Webhooks are configured once in the Sumopod dashboard (Settings > Webhook), not
per-request. Every delivery carries Svix headers (svix-id, svix-timestamp,
svix-signature) and an X-Webhook-Token header; both are verified here.
"""
import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SANDBOX_URL = "https://api-pay-sandbox.sumopod.com"
PRODUCTION_URL = "https://api-pay.sumopod.com"

# Svix timestamp tolerance (seconds) — reject replays outside this window.
WEBHOOK_TOLERANCE_SECONDS = 5 * 60

# QRIS pricing (Sumopod dashboard → Supported Payment Methods): 0.7% + Rp 300.
# "Charge fee to customer" is enabled, so the customer pays `amount + fee` and the
# merchant receives `amount` (== net_amount). This estimate is shown in the UI
# before checkout; the authoritative figure is `fee` in the create_payment response.
FEE_PERCENT = 0.7
FEE_FLAT = 300


def estimate_fee(amount: int) -> int:
    """Estimated gateway fee (IDR) the customer pays on top of ``amount``."""
    import math
    return math.ceil(int(amount) * FEE_PERCENT / 100) + FEE_FLAT


class SumopodError(Exception):
    """Raised when Sumopod returns an error or the network call fails."""


@dataclass
class PaymentResult:
    payment_url: str
    payment_id: str
    payment_code: str = ""
    fee: int = 0
    net_amount: int = 0
    status: str = ""
    expires_at: str = ""
    raw: dict = field(default_factory=dict)


# ── Webhook verification (module-level; used by the webhook view) ─────────────

def verify_svix_signature(
    secret: str,
    svix_id: str,
    svix_timestamp: str,
    svix_signature: str,
    raw_body: bytes | str,
) -> bool:
    """Return True if the Svix signature header matches.

    Mirrors Sumopod's documented Node.js example:
      secretBytes   = base64decode(secret without "whsec_")
      signedContent = f"{svix_id}.{svix_timestamp}.{raw_body}"
      expected      = base64(HMAC_SHA256(secretBytes, signedContent))
      svix-signature is space-separated "v1,<sig>" values (multiple during rotation).
    """
    if not (secret and svix_id and svix_timestamp and svix_signature):
        return False

    # Anti-replay: timestamp must be recent.
    try:
        ts = int(svix_timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > WEBHOOK_TOLERANCE_SECONDS:
        logger.warning(
            "Sumopod webhook timestamp outside tolerance: header=%s now=%s skew=%ss",
            svix_timestamp, int(time.time()), int(time.time() - ts),
        )
        return False

    if isinstance(raw_body, bytes):
        raw_body = raw_body.decode("utf-8")

    secret_bytes = base64.b64decode(secret.replace("whsec_", ""))
    signed_content = f"{svix_id}.{svix_timestamp}.{raw_body}".encode()
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode()

    passed = [part.split(",", 1)[1] for part in svix_signature.split() if "," in part]
    ok = any(hmac.compare_digest(expected, sig) for sig in passed)
    if not ok:
        logger.warning(
            "Sumopod svix signature mismatch: expected=%s… received=%s body_len=%d",
            expected[:10], [s[:10] for s in passed], len(raw_body),
        )
    return ok


def verify_webhook_token(expected: str, received: str) -> bool:
    """Constant-time comparison of the X-Webhook-Token header."""
    if not expected or not received:
        return False
    return hmac.compare_digest(expected, received)


class SumopodClient:
    def __init__(self, api_key: str, base_url: str = SANDBOX_URL,
                 webhook_secret: str = "", webhook_token: str = ""):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.webhook_secret = webhook_secret
        self.webhook_token = webhook_token

    @classmethod
    def from_settings(cls) -> "SumopodClient":
        """Instantiate from env / Setting model. Raises SumopodError if unconfigured."""
        import os

        from django.conf import settings as django_settings

        from apps.core.models import Setting

        # Secret: env ONLY — never Setting/DB.
        api_key = os.environ.get("SUMOPOD_API_KEY", "") or getattr(
            django_settings, "SUMOPOD_API_KEY", ""
        )
        webhook_secret = os.environ.get("SUMOPOD_WEBHOOK_SECRET", "") or getattr(
            django_settings, "SUMOPOD_WEBHOOK_SECRET", ""
        )
        webhook_token = os.environ.get("SUMOPOD_WEBHOOK_TOKEN", "") or getattr(
            django_settings, "SUMOPOD_WEBHOOK_TOKEN", ""
        )

        sandbox_raw = Setting.get("SUMOPOD_SANDBOX", "true") or os.environ.get(
            "SUMOPOD_SANDBOX", "true"
        )
        sandbox = str(sandbox_raw).strip().lower() != "false"
        base_url = SANDBOX_URL if sandbox else PRODUCTION_URL

        if not api_key:
            raise SumopodError(
                "Sumopod not configured: SUMOPOD_API_KEY must be set in the environment."
            )
        return cls(
            api_key=api_key,
            base_url=base_url,
            webhook_secret=webhook_secret,
            webhook_token=webhook_token,
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Sumopod's edge (Cloudflare) rejects the default urllib UA with
                # error 1010; send a normal one.
                "User-Agent": "berlanggan/1.0 (+https://berlanggan.web.id)",
                "X-Api-Key": self.api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise SumopodError(f"Sumopod HTTP {exc.code} at {path}: {body}") from exc
        except Exception as exc:
            raise SumopodError(f"Sumopod request failed at {path}: {exc}") from exc

    # ── Public API ───────────────────────────────────────────────────────────

    def create_payment(
        self,
        order_id: str,
        amount: int,
        *,
        product_details: str = "",
        email: str = "",
        success_url: str = "",
        cancel_url: str = "",
        expires_in_hours: int = 24,
        payment_method_type_code: str = "QRIS",
    ) -> PaymentResult:
        """Create a payment link. Returns the hosted payment URL + Sumopod payment id."""
        payload = {
            "order_id": order_id,
            "amount": amount,
            "currency": "IDR",
            "expires_in_hours": min(max(int(expires_in_hours), 1), 24),
            "payment_method_type_code": payment_method_type_code,
        }
        if success_url:
            payload["success_return_url"] = success_url
        if cancel_url:
            payload["cancel_return_url"] = cancel_url
        if product_details:
            payload["product_details"] = product_details
        if email:
            payload["email"] = email

        result = self._post("/api/v1/payments", payload)
        payment_url = result.get("payment_link_url", "")
        payment_id = result.get("payment_id", "")
        if not payment_url or not payment_id:
            raise SumopodError(f"Sumopod payment creation returned no link: {result}")
        return PaymentResult(
            payment_url=payment_url,
            payment_id=payment_id,
            payment_code=result.get("payment_code", ""),
            fee=int(result.get("fee", 0) or 0),
            net_amount=int(result.get("net_amount", 0) or 0),
            status=result.get("status", ""),
            expires_at=result.get("expires_at", ""),
            raw=result,
        )

    def check_status(self, order_id: str):
        """Query Sumopod for a transaction's current status.

        Not available: the Sumopod docs expose only payment creation + webhooks,
        no status-query endpoint. The safety-net task therefore only expires stale
        pending TopUps (see apps/billing/services.recheck_topup_status). If Sumopod
        adds a GET endpoint, implement it here.
        """
        raise SumopodError("Sumopod has no transaction status endpoint")

    # ── Webhook verification ─────────────────────────────────────────────────

    def verify_webhook(self, headers, raw_body: bytes | str) -> bool:
        """Verify an incoming webhook request.

        Both mechanisms are enforced when configured: if SUMOPOD_WEBHOOK_SECRET is
        set the Svix signature must pass; if SUMOPOD_WEBHOOK_TOKEN is set the token
        must match. At least one must be configured.
        """
        if not self.webhook_secret and not self.webhook_token:
            raise SumopodError(
                "Sumopod webhook not configured: set SUMOPOD_WEBHOOK_SECRET and/or "
                "SUMOPOD_WEBHOOK_TOKEN in the environment."
            )

        def _h(name: str) -> str:
            try:
                return headers.get(name, "") or ""
            except AttributeError:
                return ""

        svix_ok = None
        if self.webhook_secret:
            svix_ok = verify_svix_signature(
                self.webhook_secret,
                _h("svix-id"),
                _h("svix-timestamp"),
                _h("svix-signature"),
                raw_body,
            )

        token_ok = None
        if self.webhook_token:
            token_ok = verify_webhook_token(self.webhook_token, _h("x-webhook-token"))

        if svix_ok is False or token_ok is False:
            logger.warning(
                "Sumopod webhook verify failed: svix_ok=%s token_ok=%s "
                "(headers present: svix-id=%s svix-timestamp=%s svix-signature=%s x-webhook-token=%s)",
                svix_ok, token_ok,
                bool(_h("svix-id")), bool(_h("svix-timestamp")),
                bool(_h("svix-signature")), bool(_h("x-webhook-token")),
            )
            return False

        return True
