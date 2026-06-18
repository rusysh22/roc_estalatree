"""WhatsApp notification backend — swappable gateway abstraction.

Backend is selected via Setting key WA_BACKEND:
  "console"  — logs to stdout; default for dev/test (no credentials needed)
  "fonnte"   — Fonnte API (https://fonnte.com); requires WA_TOKEN Setting

Open question (STATUS.md): final WA gateway TBD (Fonnte / Wablas / official WABA).
Adding a new gateway = add a class implementing .send(to_number, message) + register
it in _BACKENDS. No other code changes needed.
"""
import json
import logging
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

from apps.core.models import Setting

logger = logging.getLogger(__name__)


@runtime_checkable
class WhatsAppBackend(Protocol):
    def send(self, to_number: str, message: str) -> None: ...


class ConsoleBackend:
    """Dev / test backend — logs the message. No credentials needed."""

    def send(self, to_number: str, message: str) -> None:
        logger.info("[WA-console] → %s: %s", to_number, message[:80])


class FonnteBackend:
    """Fonnte WA gateway. Requires WA_TOKEN Setting (device token from fonnte.com)."""

    API_URL = "https://api.fonnte.com/send"

    def send(self, to_number: str, message: str) -> None:
        token = Setting.get("WA_TOKEN", "")
        if not token:
            logger.warning("FonnteBackend: WA_TOKEN not configured — message not sent to %s", to_number)
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


_BACKENDS: dict[str, type] = {
    "console": ConsoleBackend,
    "fonnte": FonnteBackend,
}


def get_backend() -> WhatsAppBackend:
    key = Setting.get("WA_BACKEND", "console")
    cls = _BACKENDS.get(key, ConsoleBackend)
    return cls()


def normalize_number(raw: str) -> str:
    """Normalize Indonesian WA number: 081xxx → 6281xxx, +62xxx → 62xxx."""
    number = raw.strip().lstrip("+")
    if number.startswith("0"):
        number = "62" + number[1:]
    return number


def send_whatsapp(to_number: str, message: str) -> None:
    """Send a WA message via the configured backend. No-op if number is blank."""
    if not to_number:
        return
    get_backend().send(normalize_number(to_number), message)
