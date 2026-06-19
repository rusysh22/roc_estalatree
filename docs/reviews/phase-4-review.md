# Phase 4 Review — Catalog & Checkout

**Date:** 2026-06-18 · **Reviewer:** assistant (review-only; no code changed)
**Commit reviewed:** `a7c4cc7 Phase 4: Catalog & Checkout`
**Also confirmed:** `e41f687` applied Phase 3 fixes (H1 API key out of plaintext Setting, H2 bonus inside atomic, M1–M4). `assign_unique_public_id` present.
**Verdict:** Good structure — `Order.idempotency_key` with `IntegrityError` race handling, top-up-and-buy via `checkout_order` OneToOne, namespaced debit ref, price snapshot, contact-plan guard, provisioners registered in `ready()`. One serious HIGH and a data-linkage gap to fix now (Phase 5/6 depend on it).

## What's good (keep)
- Idempotent checkout via `Order.idempotency_key`; race handled with `IntegrityError` → return existing.
- Top-up-and-buy: pending Order linked to funding TopUp; completed on credit (ADR-015).
- Debit only via `wallet.services.debit()`, ref `order:<public_id>`; amount = plan price snapshot.
- Contact plans rejected; FREE plans handled.

---

## HIGH

### H1. Provisioning runs outside the payment transaction → "paid but not delivered"
In `checkout()` (balance path, ~line 199), `complete_pending_order` (~line 99), and the FREE path (~line 164), `_fulfill_paid_order()` / `_provision_order()` are called **after/outside** the atomic block that debits and sets the Order `PAID`. If any provisioner raises (e.g. an unregistered type like `license_key` → `KeyError`, or a future external failure), the customer is **debited and the Order is `PAID` but no Grant exists**, with no recovery path (idempotent replay returns the PAID order with whatever grants exist — possibly none). Same class of bug as Phase 3 H2, but on the core deliverable.
- **Action (Phase 4, pure-DB provisioners):** wrap `_fulfill_paid_order` **inside the same atomic** as debit + PAID (all-or-nothing). A KeyError then rolls the debit back.
- **Action (Phase 5+, external provisioners):** network I/O must NOT run inside the DB/wallet lock. Introduce a fulfillment state (e.g. `Order.fulfilled` / pending Grant) + async provisioning task + idempotent retry; make checkout replay re-attempt missing provisioning. Design this now.

---

## HIGH / MEDIUM — data linkage (fix now)

### H2. Grants are not linked to their Order; recurring Grants not linked to their Subscription
- `Grant` has no `order` FK → idempotent replay fetches grants via loose `filter(customer, deliverable__plan)`, conflating repeated purchases of the same plan; support/audit can't map grant → order. **Add `Grant.order`.**
- For recurring plans, `_create_subscription` creates a Subscription but `_provision_order` creates Grants with `subscription=None`. **Phase 6 lifecycle cascade** (suspend/resume/renew by subscription state) **won't find these grants.** Link `Grant.subscription` at provision time (pass the subscription into the provisioner).
- Fix now: Phase 5 (license_key provisioner) and Phase 6 (renewal cascade) depend on these links.

---

## MEDIUM
- **M1.** FREE path lacks `IntegrityError` handling (concurrent same-key) and provisions outside a transaction (same as H1) — make it consistent.
- **M2.** Top-up-and-buy can strand an Order: if the customer spends the freshly credited balance before `complete_pending_order` debits, `debit` raises `InsufficientBalance` and the Order stays `PENDING` forever (balance credited, not lost). Handle: surface / retry / keep recoverable.
- **M3.** `Order` is not linked to `Subscription` — add for traceability/refunds.

## LOW
- Idempotent-replay grant query becomes precise once `Grant.order` exists.
- `_create_subscription` else-branch implicitly means YEARLY — make explicit.
- Tests to add: paid-but-provision-fails (H1); repeated same-plan purchase grant mapping (H2); FREE concurrent same-key (M1); balance-spent-before-completion (M2).

---

## Suggested action mapping
| Item | When |
|------|------|
| H1 provisioning inside atomic (pure-DB) | Now |
| H1 async fulfillment + retry (external) | Phase 5 (before account/api_key provisioners) |
| H2 Grant.order + Grant.subscription links | Now (before Phase 5/6) |
| M1 FREE path consistency | Now |
| M2 strand handling | Phase 6 (jobs) |
| M3 Order↔Subscription link | Phase 5 |
