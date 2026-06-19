# 08 — Integrations & Notifications

## 8.1 Duitku (Payment / Top-up)
- Used **only** for topping up balance (money in). Not for direct product checkout.
- Methods: VA, QRIS, e-wallet, retail.
- **Flow:** create TopUp `pending` → request invoice from Duitku → redirect/QR → customer pays → **webhook callback**.
- **Webhook requirements:**
  - **Verify Duitku signature.**
  - **Idempotent** (`PaymentWebhook.idempotency_key`) — no double-credit.
  - On success → credit Wallet via the service layer (LedgerEntry `topup` + bonus if any) → notification.
- Start in **sandbox**, then production. Credentials in `Setting`/env, not hardcoded.

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
