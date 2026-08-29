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
- For customer notifications & the **Contact** button (deep link `wa.me`).
- Gateway: **kirim.chat** (ADR-022). `WA_BACKEND=kirimchat`, secret `WA_TOKEN` (env-only). Fonnte/console backends kept for fallback/dev.
- Abstraction: `notifications/whatsapp.py` — add a backend class + register in `_BACKENDS`.
- **Customer-only.** Sellers are email-only. See [27-whatsapp-notifications.md](27-whatsapp-notifications.md).

## 8.3 Email
- Primary channel and system-of-record for financial documents + **invoice PDF** delivery.
- Standard Django SMTP.

## 8.4 Notifications (event → channel)

Each customer picks **one** channel (`Customer.notification_channel`, email | whatsapp;
WhatsApp needs a verified number). Value documents are always emailed regardless.

| Event | Channel |
|-------|---------|
| Top-up success (HTML receipt) | email always · WA copy if chosen |
| Purchase success + license key (HTML receipt) | email always · WA copy if chosen |
| Renewal reminder (H-3, H-1) | chosen channel |
| Renewal success · renewal failed · low balance | chosen channel |
| License suspended / graced / cancelled | chosen channel |
| Order awaiting payment / rejected | chosen channel |
| Seller: new order needs confirmation | seller email |
| Promotions (opt-in `notif_promo`) | email only (for now) |

- Templates managed by Superadmin; WA business-initiated sends use pre-approved WABA templates.
- Delivery via **background jobs** (async), never blocking the request.
- **Delivery tracking:** `NotificationDelivery` outbox rows; kirim.chat webhook `POST /notifications/webhook/kirimchat/` (`X-KirimChat-Signature` HMAC-SHA256, `event_id` idempotency) updates status and, on `message.failed`, re-sends the notification by email. Inbound `STOP` → `WhatsAppSuppression` + channel reset to email.
