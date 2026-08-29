"""WhatsApp Business (WABA) template registry (ADR-022, N.5).

WhatsApp only allows free-text within 24h of the recipient's last inbound
message. Every business-initiated message we send (OTP, reminders, status
updates) therefore needs a **pre-approved template**.

`WA_TEMPLATE_MODE` (DB Setting) controls how sends behave:
  "off"     — always send plain text  (default; use before templates are approved)
  "on"      — send as a template when one is registered for the event + params
              were supplied; otherwise fall back to plain text
  "strict"  — same as "on" but if no template/params are available the WA send
              is skipped (the email fallback still runs via the outbox)

Each `Template.body` is the exact text to submit in the kirim.chat / Meta
template editor, with numbered placeholders. `variables` documents what each
placeholder means. Keep body text and the plain-text messages in the handlers
in sync.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Template:
    name: str
    category: str          # "authentication" | "utility"
    body: str
    variables: list[str] = field(default_factory=list)
    language: str = "en"


# event key -> Template. Several keys may share one template (e.g. reminder:h3/h1).
TEMPLATES: dict[str, Template] = {
    "otp": Template(
        "wa_otp_verification", "authentication",
        "{{1}} is your berlanggan verification code. It expires in 5 minutes. "
        "Do not share this code with anyone.",
        ["code"],
    ),
    "topup.paid": Template(
        "topup_success", "utility",
        "Top-up successful. {{1}} has been credited to your balance and is ready to use.",
        ["amount (+ bonus)"],
    ),
    "order.paid": Template(
        "order_success", "utility",
        "Purchase successful: {{1}}. Your access details:\n{{2}}\nKeep this information safe.",
        ["product name", "delivery lines"],
    ),
    "order.awaiting_confirmation": Template(
        "order_pending_payment", "utility",
        "Order received for {{1}} (Rp{{2}}). Complete the payment via the seller's QRIS; "
        "your order is processed once the seller confirms.",
        ["product name", "amount"],
    ),
    "order.payment_rejected": Template(
        "payment_rejected", "utility",
        "The seller did not receive payment for {{1}}, so the order was cancelled. "
        "Contact the seller if you have already paid.",
        ["product name"],
    ),
    "order_pending:h2": Template(
        "order_pending_nudge", "utility",
        "Your order for {{1}} (Rp{{2}}) is still awaiting payment. Complete the payment "
        "via the seller's QRIS, then wait for the seller to confirm.",
        ["product name", "amount"],
    ),
    "subscription.renewed": Template(
        "subscription_renewed", "utility",
        "Your {{1}} subscription has been renewed. Active until {{2}}.",
        ["plan name", "date"],
    ),
    "subscription.graced": Template(
        "subscription_grace", "utility",
        "Your balance was not enough to renew {{1}}. You have a {{2}}-day grace period — "
        "top up now to keep your access active.",
        ["plan name", "grace days"],
    ),
    "subscription.suspended": Template(
        "subscription_suspended", "utility",
        "Your {{1}} subscription was suspended because your balance was insufficient and "
        "the grace period ended. Top up now — access is restored automatically.",
        ["plan name"],
    ),
    "subscription.cancelled": Template(
        "subscription_ended", "utility",
        "Your {{1}} subscription has ended (auto-renew is off). Reactivate any time from "
        "your dashboard.",
        ["plan name"],
    ),
    "reminder:h3": Template(
        "renewal_reminder", "utility",
        "Your {{1}} subscription renews in {{2}}. Price Rp{{3}}, balance Rp{{4}}, "
        "shortfall Rp{{5}}. Top up now to avoid an interruption.",
        ["plan name", "time left", "price", "balance", "shortfall"],
    ),
    "expiry:d7": Template(
        "expiry_reminder", "utility",
        "Your {{1}} access ends on {{2}} ({{3}} left) and will not renew automatically. "
        "Renew from your dashboard to keep access.",
        ["plan name", "end date", "time left"],
    ),
    "grace:g2": Template(
        "grace_countdown", "utility",
        "Your {{1}} subscription is in its grace period and access suspends in {{2}}. "
        "Balance Rp{{3}}. Top up now to keep access.",
        ["plan name", "time left", "balance"],
    ),
    "low_balance": Template(
        "low_balance_alert", "utility",
        "Heads up: your balance (Rp{{1}}) won't cover the upcoming renewal of {{2}} "
        "(Rp{{3}}) on {{4}}. Top up to keep your subscription active.",
        ["balance", "plan name", "price", "renewal date"],
    ),
    "welcome": Template(
        "welcome", "utility",
        "Welcome to berlanggan, {{1}}! Your account is ready. Manage your subscriptions "
        "and balance from your dashboard.",
        ["name"],
    ),
}

# Aliases: reuse one approved template across related event keys.
_ALIASES = {
    "reminder:h1": "reminder:h3",
    "expiry:d3": "expiry:d7",
    "expiry:d1": "expiry:d7",
    "grace:g1": "grace:g2",
    "order_pending:h24": "order_pending:h2",
}


def get_template(event_key: str) -> Template | None:
    key = _ALIASES.get(event_key, event_key)
    return TEMPLATES.get(key)


def template_mode() -> str:
    from apps.core.models import Setting
    mode = Setting.get("WA_TEMPLATE_MODE", "off").strip().lower()
    return mode if mode in ("off", "on", "strict") else "off"


def all_templates_for_submission() -> list[Template]:
    """Unique templates to submit for approval (dedups aliases)."""
    seen = {}
    for t in TEMPLATES.values():
        seen[t.name] = t
    return sorted(seen.values(), key=lambda t: (t.category, t.name))
