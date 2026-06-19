# Phase 3 Review — Top-up (Duitku)

**Date:** 2026-06-18 · **Reviewer:** assistant (review-only; no code changed)
**Commit reviewed:** `cec5fbf phase3: top-up (Duitku)`
**Also confirmed:** `6eca2ef` applied Phase 2 fixes (MH1 ref namespacing — used here as `topup:`/`bonus:`; MH2 Postgres tests; M1/M2/L1-L3).
**Verdict:** Mature. Correct MD5 signature, webhook idempotency via unique `PaymentWebhook` + `IntegrityError` backstop, `select_for_update` on TopUp, Celery safety-net poll, credit taken from trusted `topup.amount` (not the webhook-claimed number). Two HIGH items to fix before Phase 4.

## What's good (keep)
- Signatures match Duitku docs (inquiry, transactionStatus, callback).
- Wallet credited only via `wallet.services.credit()`; refs namespaced.
- Webhook returns 200/400/500 deliberately to control Duitku retry behaviour.
- Safety-net `poll_pending_topups` (acks_late, retries, `.iterator()`, `select_related`).
- Idempotent apply via TopUp lock + idempotent `credit()`.

---

## HIGH

### H1. Duitku API key read as plaintext from `Setting` (secret trap)
`DuitkuClient.from_settings()` reads `DUITKU_API_KEY` from the `Setting` model (plaintext in DB) **with priority over env** — exactly the trap documented in [../23-configuration.md](../23-configuration.md). A secret in the DB leaks via backups/dumps/admin.
- **Action:** read the **API key from env only**, or if it must be UI-editable, store in an **encrypted field** (Fernet/KMS). Merchant code may stay in `Setting`; the API key must not be plaintext.

### H2. Bonus credit can be permanently lost (money correctness)
In `_apply_topup_success`, the **bonus credit runs outside** the `transaction.atomic()` block (after `status=PAID` is committed). If the bonus credit fails/crashes afterwards there is **no retry path**: a duplicate webhook short-circuits at the idempotency gate (never re-calls `_apply`), and the safety-net `recheck_topup_status` returns early because status is already `PAID`. The bonus is lost forever.
- **Action:** move the bonus credit **inside the same atomic block** (all-or-nothing with the top-up). The `bonus:<id>` ref keeps it idempotent.

---

## MEDIUM

### M1. Paid amount not cross-checked against `topup.amount`
A valid signature only proves the amount came from Duitku, not that it equals the order. On mismatch (e.g. underpayment) the system still credits the full `topup.amount`. Same on the safety-net path (`status.amount` not compared).
- **Action:** assert webhook `amount == topup.amount` (and `status.amount == topup.amount`) before applying; on mismatch, do not auto-credit — surface to System Health.

### M2. `idempotency_key = duitku:<merchantOrderId>` masks status-transition callbacks
If a non-success callback is recorded first, a later **success** callback for the same order is treated as a duplicate and never processed (credit via webhook never happens; the safety-net poll is the only rescue).
- **Action:** include `resultCode`/`reference` in the idempotency key, or only dedupe when the prior callback was a success.

### M3. "TopUp not found" returns 200
Hides a real anomaly (race / replication lag / wrong order id) and stops Duitku retrying.
- **Action:** surface to System Health; consider returning 500 for the not-found case if a race is plausible.

### M4. No local expiry handling
Invoice `expiryPeriod=1440` but a pending TopUp is never marked `EXPIRED` locally unless Duitku reports failed → polled forever.
- **Action:** mark `EXPIRED` after the expiry window.

---

## LOW
- `int(payload["amount"])` can break on decimal/odd string input — parse defensively.
- Consider an IP allowlist for Duitku callbacks (extra layer; signature already sufficient).
- Add tests: bonus-credit failure (H2), amount mismatch (M1), non-success-then-success callback (M2).

---

## Suggested action mapping
| Item | When |
|------|------|
| H1 API key out of plaintext Setting | Now |
| H2 bonus inside atomic | Now (money correctness) |
| M1 amount cross-check | Phase 4 (before checkout reuses patterns) |
| M2 idempotency key includes status | Phase 4 |
| M3 surface not-found | Phase 10 (System Health) |
| M4 expiry handling | Phase 6 (jobs) |
| LOW | As convenient |
