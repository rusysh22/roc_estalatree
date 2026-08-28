# 08 — Integrations & Notifications

## 8.1 Sumopod (Payment / Top-up)
- Used **only** for topping up balance (money in) and direct-pay checkout. See ADR-021.
- Methods: **QRIS** (sandbox). Other methods shown as "under maintenance" in the UI.
- **Client:** `apps/billing/sumopod.py`. **Flow:** create TopUp `pending` → `POST /api/v1/payments` → redirect to `payment_link_url` → customer pays → **webhook**.
- **Webhook** (`/billing/webhook/sumopod/`, configured once in the Sumopod dashboard):
  - Verify **both** the Svix signature (`SUMOPOD_WEBHOOK_SECRET`) **and** `X-Webhook-Token` (`SUMOPOD_WEBHOOK_TOKEN`).
  - **Idempotent** via `PaymentWebhook.idempotency_key = sumopod:<svix-id>` — no double-credit.
  - Events: `payment.completed` → credit Wallet (LedgerEntry `topup` + bonus) → notification; `payment.failed` / `payment.expired` → mark TopUp FAILED/EXPIRED; `payment.test` → no-op.
  - Amount cross-check: `webhook.data.amount == topup.amount` (fee passthrough is enabled, so the customer pays `amount + fee`).
- No transaction-status endpoint: the safety-net task only expires stale pending top-ups.
- Secrets are **env-only** (`SUMOPOD_API_KEY`, `SUMOPOD_WEBHOOK_SECRET`, `SUMOPOD_WEBHOOK_TOKEN`), never `Setting`/DB. Start in **sandbox** (`SUMOPOD_SANDBOX=True`).

## 8.2 WhatsApp
- For notifications & the **Contact** button (deep link `wa.me`).
- Notification gateway candidates: **Fonnte / Wablas** (common in ID) or the official WhatsApp Business API. **Final choice at implementation time** (see risks).
- Abstraction: a `notifications/whatsapp.py` with a generic interface so the gateway is swappable.

## 8.3 Email
- Companion/fallback for notifications + **invoice PDF** delivery.
- Standard Django SMTP.

## 8.4 Notifications (event → channel)

| Event | WA | Email |
|-------|----|----|
| Top-up success | ✓ | ✓ |
| Purchase success + license key | ✓ | ✓ |
| Renewal reminder (H-3, H-1) | ✓ | ✓ |
| Renewal success | ✓ | — |
| Renewal failed (insufficient balance) | ✓ | ✓ |
| Low balance | ✓ | — |
| License suspended | ✓ | ✓ |
| Lead follow-up | ✓ | — |

- Templates managed by Superadmin (in `Setting` / a template model).
- Delivery via **background jobs** (async), never blocking the request.
