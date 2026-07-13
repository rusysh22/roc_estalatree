# 25 — License Key, Webhook & Activation API: End-to-End Guide

> **Audience:** this doc has two halves. **Part A** is for the **Customer Success / Ops team** — no code, just "what happens when" and how to troubleshoot a customer report. **Part B** is for **developers** integrating an on-prem product with the Activation API, or maintaining the webhook/licensing code. Read [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md) and [14-state-machines.md](14-state-machines.md) alongside this for the underlying data model and status rules — this doc focuses on the *flow* connecting them.

---

## Part A — The flow, in plain terms

### What is a "license key" here?

Every purchase of a licensed plan (e.g. RoC Support Desk Starter/Professional/Enterprise) generates one **License Key** — a code shaped like `XXXX-XXXX-XXXX`. The customer pastes this key into the product's own activation screen (inside RoC Support Desk itself, not on our site) to unlock it. One key can be shared across a limited number of devices at once (the plan's **seat limit**) — e.g. a 2-seat plan lets the customer activate on 2 machines; a 3rd activation attempt is rejected until they free up a seat.

### The journey from "customer pays" to "customer has a working license"

```
1. Customer checks out (wallet balance, or tops up first)
        │
2. If a top-up was needed → customer pays via Duitku (VA/QRIS/e-wallet/retail)
        │
3. Duitku sends us a WEBHOOK confirming the payment
        │
4. Our system verifies the webhook, credits the wallet, marks the Order "paid"
        │
5. A License Key is generated automatically and attached to the order
        │
6. Customer is notified: WhatsApp + Email (with a PDF invoice attached)
        │        also visible immediately in the customer's Dashboard → "License Keys"
        │
7. Customer copies the key into their RoC Support Desk activation screen
        │
8. RoC Support Desk calls our Activation API (behind the scenes) to activate it
        │
9. From then on, the product periodically "checks in" (heartbeat) with us
   to confirm the license is still valid
```

If the customer already had enough wallet balance, steps 2–3 are skipped — the order is paid and the license is generated **instantly** at checkout.

### Where things live for support/ops

- **Customer Dashboard** (customer-facing): shows the license key (copyable), which devices are activated, and lets the customer release a device seat themselves (e.g. after replacing a laptop).
- **Console / Customer 360** (internal, ops-facing): search a customer, see their orders, subscriptions, and licenses in one place; suspend/resume/revoke a license from here when needed (e.g. chargeback, abuse, manual refund).
- **Admin → Settings**: a few knobs ops can change **without a deploy** — see [23-configuration.md](23-configuration.md). The ones relevant here:
  - `MAINTENANCE_MODE` — flip to `true` during an incident so the Activation API never rejects a customer's product (it always reports "active") while we fix things.
  - `GLOBAL_GRACE_EXTENSION_DAYS` — give everyone extra grace days at once (e.g. payment provider outage).
  - `ACTIVATION_API_SECRET` — optional shared secret product builds must send; leave empty unless a developer asks you to set it.

### Why does the license sometimes get suspended automatically?

Recurring plans (monthly/yearly) auto-renew from the customer's wallet balance. If the balance is too low on the renewal date:
1. The subscription enters a short **grace period** (customer gets a WA/email reminder) — license still works.
2. If the customer tops up in time, it auto-recovers, no action needed.
3. If the grace period lapses, the subscription and its license get **suspended** automatically. The customer just needs to top up and the system reactivates it on the next check — no manual intervention needed 99% of the time.

Full status rules: [14-state-machines.md](14-state-machines.md) (see "Subscription" and "License" sections).

### Common support scenarios

| Customer says... | What's actually happening | What to check |
|---|---|---|
| "I paid but never got my license key" | Either the Duitku webhook hasn't arrived yet (rare, usually resolves within minutes via our polling safety-net), or notifications failed (WA/email misconfigured for that customer, or address suppressed). | Check the order status in Console. If `paid`, the license already exists — pull it from Console/Dashboard and send it manually. If still `pending`, wait a few minutes; escalate to dev if it stays pending >15 min. |
| "My license says suspended" | Recurring plan renewal failed due to low wallet balance and grace period lapsed. | Confirm in Console. Ask the customer to top up; it self-heals on the next balance top-up. No manual reactivation needed. |
| "Activation says seat full" | The plan's device limit is reached. | Check Console for that license's active installations. Have the customer deactivate an old device from their Dashboard, or manually release one from Console if they can't access the old machine. |
| "My activation token / product stopped working after an update" | Possibly the product's local token expired and it hasn't re-validated yet, or (rarely) `MAINTENANCE_MODE` was left on. | Ask them to relaunch the product (triggers a fresh heartbeat). If it's a platform-wide issue, check `MAINTENANCE_MODE`/`GLOBAL_GRACE_EXTENSION_DAYS` in Admin. |
| "I want to move my license to a new laptop" | Normal seat management — not a bug. | Guide them to Dashboard → deactivate the old device, then activate on the new one. |

---

## Part B — Technical reference (developers)

### System overview

```
Customer's product (e.g. RoC Support Desk installed on-prem)
        │  HTTPS + JSON
        ▼
  /v1/activate  /v1/validate  /v1/deactivate      ← our Activation API (Django Ninja)
        │
        ▼
  apps/licensing (License, Installation)  ←→  apps/provisioning (Grant, Deliverable, Entitlement)
        ▲
        │  provisioned on Order.paid
        │
  apps/billing (Order, Subscription, TopUp) ←── webhook ── Duitku (payment gateway)
```

License keys are one specific case of a more general **Deliverable → Provisioner → Grant** pipeline; see [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md) if you're adding a new deliverable type. This doc only covers the license-key path and the two HTTP surfaces (incoming payment webhook, outgoing-facing Activation API).

### B1. Incoming webhook — Duitku payment callback

This is the **only** incoming webhook in the system. It doesn't touch licenses directly — it confirms payment, which is what *triggers* license generation for "top-up-and-buy" checkouts.

- **Endpoint:** `POST /billing/webhook/duitku/` — `apps/billing/views.py:16` `duitku_webhook()`
- **Content type:** `application/x-www-form-urlencoded` (Duitku's real format; JSON is accepted as a fallback for test tooling)
- **Configure in Duitku's merchant dashboard:** callback URL = `https://<your-domain>/billing/webhook/duitku/` (see `DUITKU_CALLBACK_URL` in `.env.example`)

**Signature verification** (`apps/billing/duitku.py:247`):
```
expected_signature = MD5(merchantCode + amount + merchantOrderId + DUITKU_API_KEY)
```
If the payload's `signature` field doesn't match, the endpoint returns **400** and the callback is discarded — not retried, because a bad signature is never going to become valid on retry.

**Idempotency:** every callback is keyed as `duitku:{merchantOrderId}:{resultCode}` and recorded in `PaymentWebhook.idempotency_key` (unique constraint). Duitku commonly fires the same result more than once — duplicates are detected and short-circuited safely, no double-crediting. A later *success* callback for an order that previously got a *non-success* callback is still processed (the resultCode is part of the key), so a late "payment confirmed" after an earlier "pending"/"failed" ping isn't lost.

**Amount cross-check:** before crediting, the webhook handler compares the callback's claimed amount against the amount we expect for that `TopUp` — protects against a tampered or replayed payload trying to credit the wrong amount.

**HTTP response contract** (Duitku uses this to decide whether to retry):
| Response | Meaning | Duitku behavior |
|---|---|---|
| `200 OK` | Processed (success or a recognized non-success result) | Stops sending this callback |
| `400 Bad Request` | Signature invalid | Stops (nothing to retry) |
| `500 Internal Server Error` | Order not found yet (replication lag) or unexpected error | Retries later — **this is intentional**, don't "fix" it into a 200 |

**Safety net:** a Celery job (`apps/billing/tasks.py`, calling `apps/billing/services.py` `recheck_topup_status()`) actively polls Duitku's `transactionStatus` API for any `TopUp` whose webhook never arrived, using the same signature/amount logic. So a lost webhook is not a dead end.

**What happens after a successful webhook:** wallet is credited → if the top-up was funding a pending order/cart checkout, `complete_pending_order()` / `complete_cart_checkout()` runs the same provisioning path as a direct-balance checkout, generating the license (or other deliverable) and emitting `order.paid` (see [08-integrations.md](08-integrations.md) for the full notification matrix).

**There is no outgoing webhook** from us to the customer's product or to third parties. Delivery of the license key to the customer is via email/WhatsApp (push) and the Dashboard (pull); the product itself *pulls* license status via the Activation API described below, it is never pushed to.

### B2. Activation API (for the licensed product to call)

Base path: **`/v1`**. All three endpoints return **HTTP 200** with a `status` field in the body — this is the standard convention for activation APIs (like Keygen/Cryptlex), so a non-200 always means transport-level failure, not "invalid license."

**Auth:** optional header `X-Berlanggan-Secret`, checked against the `ACTIVATION_API_SECRET` Admin Setting (`apps/licensing/api.py:21`, `ProductSecretAuth`). If that Setting is left empty (the default), **all requests are allowed** — this is a deliberate "license-key-as-sole-credential" mode. Set the Setting if you want an extra shared-secret layer per deployment.

**Rate limits** (per `apps/licensing/services.py:14`):
- `/activate`, `/deactivate`: 10 requests / 60s per license key, 120/60s per IP
- `/validate`: 60 requests / 60s per license key (accounts for multi-seat heartbeats), 120/60s per IP
- Exceeding a limit returns `{"status": "rate_limited"}` — the product should back off and retry later, not hammer the endpoint.

#### `POST /v1/activate`

Registers a device (identified by a machine `fingerprint`, e.g. a hash of hardware IDs) against a license and issues a signed activation token.

```bash
curl -X POST https://<domain>/v1/activate \
  -H "Content-Type: application/json" \
  -H "X-Berlanggan-Secret: <optional>" \
  -d '{"license_key": "XXXX-XXXX-XXXX", "fingerprint": "sha256-of-hw-id", "machine_name": "DESKTOP-01"}'
```

Response (`ActivationResponse` schema — `apps/licensing/api.py:66`):
```json
{
  "status": "active", "token": "<signed>", "expires_at": "2026-08-01T00:00:00Z", "grace_days": 3,
  "entitlements": {"MAX_AGENTS": 10, "WHATSAPP": true},
  "entitlement": {"license_id": "XXXX-XXXX-XXXX", "fingerprint": "sha256-of-hw-id", "product_id": "roc-support-desk", "status": "active", "issued_at": "2026-07-13T00:00:00Z", "expires_at": "2026-08-01T00:00:00Z", "entitlements": {"MAX_AGENTS": 10, "WHATSAPP": true}},
  "entitlement_signature": "base64-ed25519-signature"
}
```

`entitlement` + `entitlement_signature` (`apps/licensing/entitlement_signing.py`) let a product build verify the response wasn't tampered with, using a public key baked into its own release — see that product's own signed-entitlements contract doc for the client-side verification rules. The Marketplace's private key lives only in `MARKETPLACE_ED25519_PRIVATE_KEY_B64` (env, never the `Setting` model/DB — same handling as `DUITKU_API_KEY`). If unset, `entitlement_signature` comes back `""` (dev convenience) — a product build that has a public key configured must treat an unsigned or invalid-signature response as untrusted rather than as "still active".

Possible `status` values: `active` (success) · `invalid` (key not found) · `revoked` · `suspended` · `expired` · `seat_full` · `rate_limited`. On `seat_full`, `message` tells the caller how many seats exist so the product can show a useful error to the user.

**Idempotent:** calling `/activate` again with the same `fingerprint` on the same license does not consume a second seat — it just refreshes `last_seen` and returns a new token.

**Concurrency:** seat-limit enforcement locks the `License` row (`select_for_update`) inside a transaction, so two simultaneous activation requests for the last free seat can't both succeed (no seat overflow race).

#### `POST /v1/validate` (heartbeat)

The product should call this periodically (e.g. on launch, and every N hours) to confirm it's still allowed to run and to refresh its token before expiry.

```bash
curl -X POST https://<domain>/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"license_key": "XXXX-XXXX-XXXX", "fingerprint": "sha256-of-hw-id", "token": "<previously-issued-token>"}'
```

Response: same `ActivationResponse` shape. `status` values: `active` · `grace` (token expired but within the grace window — treat as active, but nudge the product to re-validate soon) · `expired` (must call `/activate` again) · `invalid` (bad/tampered token) · `revoked` · `suspended` · `deactivated` (this fingerprint's seat was released — e.g. from the Dashboard — so the product must re-activate to reclaim a seat) · `rate_limited`.

Notes for implementers:
- The token is a `django.core.signing.TimestampSigner` HMAC value, not a JWT — treat it as opaque on the product side, just store and resend it.
- **Sliding expiry:** every successful `validate` returns a fresh token, so as long as the product calls in periodically before its token's TTL (default 7 days, `ACTIVATION_TOKEN_TTL_DAYS`) it never has to re-activate.
- `entitlements` comes back on every successful `active` response — use it for local feature gating (e.g. hide/disable a feature the customer's plan doesn't include) instead of hardcoding tiers in the product.
- **`MAINTENANCE_MODE`** (Admin Setting): when `true`, `/validate` always returns `active` regardless of real state — a deliberate "never brick a customer's install during our incident" switch. Products should treat this transparently; there's nothing special to implement.

#### `POST /v1/deactivate`

```bash
curl -X POST https://<domain>/v1/deactivate \
  -H "Content-Type: application/json" \
  -d '{"license_key": "XXXX-XXXX-XXXX", "fingerprint": "sha256-of-hw-id"}'
```

Response: `{"status": "deactivated"}`. Idempotent — safe to call even if the fingerprint was already deactivated (e.g. product's uninstaller calling this defensively). Frees the seat so another device (or the same one, later) can activate.

### B3. Sequence diagram — full purchase-to-heartbeat lifecycle

```
Customer      Storefront        Duitku        Backend (billing/licensing)     Product install
   │               │               │                     │                        │
   │──checkout────>│               │                     │                        │
   │               │──(if short)──>│  create invoice     │                        │
   │<──pay link/QR─┤               │                     │                        │
   │──pay──────────────────────────>│                     │                        │
   │               │               │──webhook (signed)──>│                        │
   │               │               │                     │ verify sig, idempotent, │
   │               │               │                     │ credit wallet,         │
   │               │               │                     │ mark Order paid,       │
   │               │               │                     │ generate License       │
   │               │               │                     │──emit order.paid──┐    │
   │               │               │                     │                   ▼    │
   │<─────────────────────── WhatsApp + Email (license key + invoice PDF) ────────┤
   │               │                                                          │   │
   │──paste key into product────────────────────────────────────────────────────>│
   │               │                                                          │──activate──>│ (creates Installation, returns token)
   │               │                                                          │<─active─────┤
   │               │                                            (periodically)│──validate──>│ (refreshes token)
   │               │                                                          │<─active─────┤
```

### B4. Configuration reference (developer-facing)

Full table: [23-configuration.md](23-configuration.md). The subset relevant to this flow:

| Key | Where | Purpose |
|---|---|---|
| `DUITKU_MERCHANT_CODE` | `Setting` or env | Duitku merchant identifier |
| `DUITKU_API_KEY` | **env only, never DB** (`apps/billing/duitku.py`) | Used to sign/verify webhook + invoice calls — deliberately excluded from the DB-backed `Setting` model so it can't leak via Admin/DB backup |
| `DUITKU_CALLBACK_URL` | env | Must match what's registered in Duitku's merchant dashboard |
| `DUITKU_SANDBOX` | `Setting` or env | Toggle sandbox vs production Duitku API |
| `ACTIVATION_API_SECRET` | `Setting` | Optional shared secret for `X-Berlanggan-Secret` |
| `ACTIVATION_TOKEN_TTL_DAYS` (default 7) | `Setting` | Normal token lifetime before a heartbeat is required |
| `ACTIVATION_GRACE_DAYS` (default 3) | `Setting` | Extra days a stale token is still accepted as `grace` |
| `GLOBAL_GRACE_EXTENSION_DAYS` (default 0) | `Setting` | Superadmin panic lever — extends grace for everyone at once |
| `MAINTENANCE_MODE` (default false) | `Setting` | Forces `/validate` to always report active |
| `WA_BACKEND` / `WA_TOKEN` | env | WhatsApp delivery of the license key (Fonnte) |
| `MARKETPLACE_ED25519_PRIVATE_KEY_B64` | **env only, never DB** (`apps/licensing/entitlement_signing.py`) | Signs the `entitlement` envelope in Activation API responses. Ship the matching public key to the product build |

### B5. Related docs

- [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md) — the generalized Deliverable/Provisioner/Grant model license keys are one instance of
- [14-state-machines.md](14-state-machines.md) — valid status transitions for License, Subscription, Installation
- [08-integrations.md](08-integrations.md) — Duitku/WhatsApp/Email integration overview and full notification matrix
- [06-data-model.md](06-data-model.md) — entity relationships
- [23-configuration.md](23-configuration.md) — the three config tiers (.env / DB `Setting` / per-record)
