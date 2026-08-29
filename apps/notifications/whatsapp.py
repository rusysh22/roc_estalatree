"""WhatsApp notification backend — swappable gateway abstraction.

Backend is selected via Setting key WA_BACKEND:
  "console"    — logs to stdout; default for dev/test (no credentials needed)
  "fonnte"     — Fonnte API (https://fonnte.com); requires WA_TOKEN env var
  "kirimchat"  — kirim.chat API (production gateway, ADR-022); requires WA_TOKEN env var

Adding a new gateway = add a class implementing .send(to_number, message) + register
it in _BACKENDS. No other code changes needed.
"""
import json
import logging
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class WhatsAppBackend(Protocol):
    def send(self, to_number: str, message: str) -> None: ...


class ConsoleBackend:
    """Dev / test backend — logs the message. No credentials needed."""

    def send(self, to_number: str, message: str) -> None:
        logger.info("[WA-console] → %s: %s", to_number, message[:80])


class FonnteBackend:
    """Fonnte WA gateway. Requires WA_TOKEN env var (device token from fonnte.com).

    H1: WA_TOKEN is a secret API credential — read from env only, never DB Setting.
    """

    API_URL = "https://api.fonnte.com/send"

    def send(self, to_number: str, message: str) -> None:
        import os
        token = os.environ.get("WA_TOKEN", "")
        if not token:
            logger.warning("FonnteBackend: WA_TOKEN env var not set — message not sent to %s", to_number)
            return

        payload = json.dumps({"target": to_number, "message": message}).encode()
        req = urllib.request.Request(
            self.API_URL,
            data=payload,
            headers={"Authorization": token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()
                logger.info("FonnteBackend: sent to %s — response: %s", to_number, body[:120])
        except urllib.error.URLError as exc:
            logger.error("FonnteBackend: send failed to %s: %s", to_number, exc)
            raise


class KirimChatBackend:
    """kirim.chat WA gateway (ADR-022). Requires WA_TOKEN env var (kc_live_… API key).

    Docs: https://docs.kirim.chat/developers
    Text send only for now; template sends (message_type="template") land with
    the WABA template work — see docs/27-whatsapp-notifications.md §C8.

    WA_TOKEN is a secret API credential — read from env only, never a DB Setting
    (same rule as FonnteBackend).
    """

    API_URL = "https://api-prod.kirim.chat/api/v1/public/messages/send"

    def send(self, to_number: str, message: str) -> None:
        import os
        token = os.environ.get("WA_TOKEN", "")
        if not token:
            logger.warning(
                "KirimChatBackend: WA_TOKEN env var not set — message not sent to %s", to_number
            )
            return

        payload = json.dumps({
            "phone_number": to_number,
            "channel": "whatsapp",
            "message_type": "text",
            "content": message,
        }).encode()
        req = urllib.request.Request(
            self.API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()
                logger.info("KirimChatBackend: sent to %s — response: %s", to_number, body[:160])
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode()[:200]
            except Exception:
                pass
            logger.error("KirimChatBackend: HTTP %s for %s: %s", exc.code, to_number, detail)
            raise
        except urllib.error.URLError as exc:
            logger.error("KirimChatBackend: send failed to %s: %s", to_number, exc)
            raise


_BACKENDS: dict[str, type] = {
    "console": ConsoleBackend,
    "fonnte": FonnteBackend,
    "kirimchat": KirimChatBackend,
}


def get_backend() -> WhatsAppBackend:
    key = Setting.get("WA_BACKEND", "console")
    cls = _BACKENDS.get(key, ConsoleBackend)
    return cls()


def normalize_number(raw: str) -> str:
    """Normalize Indonesian WA number: 081xxx → 6281xxx, +62xxx → 62xxx.

    Thin alias over the shared validator helper so callers keep importing it
    from here.
    """
    from apps.core.validators import normalize_wa_number
    return normalize_wa_number(raw)


def send_whatsapp(to_number: str, message: str) -> None:
    """Send a WA message via the configured backend. No-op if number is blank."""
    if not to_number:
        return
    get_backend().send(normalize_number(to_number), message)
