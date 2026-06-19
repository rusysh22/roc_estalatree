# 03 — Core Concepts (The Spine)

These two subsystems are Estalatree's backbone. Every other module depends on them.

---

## 3.1 Balance System (Wallet & Ledger)

### Rules
- Each customer has **one Wallet** with a `balance` field.
- **Top-up** via Duitku → webhook (idempotent + signature verified) → balance increases → one **LedgerEntry** recorded.
- All purchases & renewals **deduct** from balance. `balance` **must never go negative**.
- **LedgerEntry is IMMUTABLE**: every balance change has exactly one row (topup, purchase, renewal, refund, adjustment, bonus). Balance is always consistent with `SUM(ledger)`.
- Optional promos: top-up bonus (pay 100k get 110k), minimum top-up.

### Liability (important!)
The total of all customer balances is the **platform's liability (debt)**, not revenue. Money becomes revenue only when balance is spent on a product. The Superadmin dashboard shows **balance float (liability)** separately from **revenue recognized**.

### Implementation (mandatory standard)
- All balance mutations go through the **service layer** (`wallet/services.py`), **never** directly in views/models.
- Credit/debit operations are **atomic** (`transaction.atomic()` + `select_for_update()` on the Wallet).
- **Idempotency**: every mutation has a unique `ref` (e.g. top-up / order id) to prevent double-posting.
- `balance_after` is stored on each LedgerEntry for fast audit (double-entry-style).

---

## 3.2 Token / Activation Engine

### Rules
- A **License Key** is issued per Order/Subscription (plain hash `XXXX-XXXX-XXXX`, no prefix).
- The **Plan** defines the **seat limit** (number of allowed installations).
- **Online** validation: OSS products need internet to activate and heartbeat.

### API flow
1. **`POST /v1/activate`** — the product sends `license_key` + installation `fingerprint` → server checks: key valid? subscription active? seat available? → registers the **Installation** + issues a **short-lived token**.
2. **`POST /v1/validate`** (heartbeat) — the product checks periodically → server replies `active / expired / revoked / suspended`.
3. **`POST /v1/deactivate`** — release an installation (to move machines / free a seat).

### Token
- **Short TTL** (default 7 days) + **grace period** (tolerant of brief offline).
- **Revocable in real time** → next heartbeat is rejected → product locks itself.
- The token is signed so it cannot be forged; the product caches status for offline tolerance.

### Installation fingerprint
- Identifies the instance (machine/installation). Must be stable enough (not changing on minor updates) yet hard to forge. The final strategy is defined at implementation time — see risks in [10-non-functional.md](10-non-functional.md).

### Relationship with balance
Subscription lapses & balance insufficient to renew → Subscription `suspended` → License `suspended` → API replies `suspended` → product locks itself. Once the customer tops up & renews → automatic reactivation.

> Note: the license key is one **Grant** type within the generalized provisioning model — see [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md).
