# Phase 2 Review — Wallet & Ledger

**Date:** 2026-06-18 · **Reviewer:** assistant (review-only; no code changed)
**Commit reviewed:** `d4031f4 phase2: wallet service layer + ledger tests`
**Also confirmed:** `ad8295e` applied Phase 1 fixes — H1 (custom User), H2 (model-level immutability, correct: insert allowed / update+delete raise), H4 (events via `transaction.on_commit`, side-effects-only), M3, L1.
**Verdict:** Very strong. Textbook atomicity/locking, in-lock idempotency re-check, invariant tested, model-level immutability, rich tests incl. concurrency. Items below are best-practice refinements.

## What's good (keep)
- `credit()`/`debit()`: `transaction.atomic()` + `select_for_update()`; positive-amount validation; `balance_after` stored; `update_fields` on save.
- Idempotency: fast-path read + **re-check inside the lock** (correct pattern).
- `InsufficientBalance` on overdraw; debit-to-zero allowed.
- H3: Wallet auto-created via `post_save` signal (`get_or_create`, idempotent).
- Tests: invariant, credit/debit, idempotency, overdraw, zero/negative, immutability, concurrency, auto-wallet.

---

## MEDIUM-HIGH

### MH1. Idempotency returns an existing entry without verifying it matches the request
When `ref` already exists, the service returns it **without checking** that `wallet`, `type`, and amount sign match the requested operation. If a `ref` is ever reused across different operations (e.g. a `debit` reuses a prior `credit` ref, or two orders with different amounts), the second call **silently "succeeds" returning the wrong entry** — a silent money bug.
- **Action:** (a) convention — callers namespace refs (`topup:<id>`, `order:<id>`, `renewal:<sub>:<period>`); **and** (b) defensive guard — when an existing entry is found, assert `wallet_id` matches and (`type`, amount sign) match expectation; raise on mismatch.

### MH2. Concurrency test can pass falsely on SQLite
`select_for_update()` is a **no-op on SQLite** (no row locking). If the suite runs on SQLite, `test_concurrent_credits_are_serialised` passes for the wrong reason and the locking guarantee is not actually exercised.
- **Action:** run money/concurrency tests on **PostgreSQL** (prod parity). Verify the test database engine; gate this test to Postgres if needed.

---

## MEDIUM

### M1. `entry_type` is an unvalidated free string
An invalid type would persist (Django doesn't enforce `choices` at the DB level).
- **Action:** `if entry_type not in LedgerEntry.Type.values: raise ValueError(...)` in both `credit()` and `debit()`.

### M2. IntegrityError backstop on `create()`
In the very rare race that slips past the in-lock re-check (or a same-ref/different-wallet misuse), `create()` raises `IntegrityError` instead of gracefully returning the existing entry.
- **Action:** catch `IntegrityError` on create as a final idempotency backstop (re-fetch and return existing).

---

## LOW
- **L1.** The service updates the locked copy, not the caller's `wallet` instance → caller's in-memory object is stale. Document "refresh the wallet if reused after credit/debit." (Tests already `refresh_from_db`.)
- **L2.** Add tests: same-`ref` concurrent (two threads, one ref → exactly one entry); cross-operation ref reuse (guards MH1); invalid `entry_type` rejected (after M1).
- **L3.** `InsufficientBalance` docstring says "below zero" — cosmetic wording; balance is already non-negative by field type, the service guard is the real protection.

---

## Suggested action mapping
| Item | When |
|------|------|
| MH1 ref-match guard + namespacing | Phase 3 (before topup/checkout call credit/debit) |
| MH2 Postgres for money tests | Now (CI config) |
| M1 entry_type validation | Phase 3 |
| M2 IntegrityError backstop | Phase 3 |
| L1–L3 | As convenient |
