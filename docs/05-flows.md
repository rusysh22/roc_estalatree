# 05 — End-to-End Flows (Upstream → Downstream)

## 5.1 Upstream — Money In
1. Customer registers/logs in.
2. Top up balance → choose amount → Duitku (VA/QRIS/e-wallet/retail) → pay.
3. Duitku webhook (**idempotent** + **signature verified**) → balance increases → LedgerEntry + notification.

## 5.2 Middle — Provisioning
4. Customer picks a product/plan → checkout → **deduct balance** → create **Order** → run provisioner(s) → issue **Grant(s)** (e.g. License Key), and create:
   - a **Subscription** (recurring), or
   - a **permanent License** (one-time), or
   - an **instant grant** (free).
5. Customer installs the OSS product → `POST /v1/activate` (sends fingerprint) → registers **Installation** + token.
6. Product **heartbeats** → `POST /v1/validate` → status.

## 5.3 Recurring Cycle
7. **H-3** before due date → a background job checks balance:
   - **Sufficient** → auto-deduct → extend `current_period_end` → LedgerEntry + success notification.
   - **Insufficient** → WA/email reminder → **grace period** → still short → **suspend** Subscription & License → product locks itself.
8. Customer tops up → reactivation job → subscription & license active again.

## 5.4 Downstream — Edge & Support
9. Edge scenarios:
   - **Refund** → credit balance (LedgerEntry type `refund`, audited, Superadmin approval).
   - **Cancel subscription** → `auto_renew=false`, active until period end.
   - **Transfer license / change device** → deactivate old installation, free the seat.
   - **Revoke (abuse)** → License `revoked` → product locks itself.
   - **Contact lead** → WA follow-up → convert to a manual order/invoice.

## Quick diagram

```
Top-up (Duitku) ──> Balance (+ledger)
                       │
                  Checkout (−ledger) ──> Order ──> Grant (License Key / ...)
                                                      │
                                          activate ──> Installation + token
                                                      │
                                          validate (heartbeat) ──> active/expired/...
                                                      │
                      Renewal job ── balance sufficient? ──> extend / suspend
```
