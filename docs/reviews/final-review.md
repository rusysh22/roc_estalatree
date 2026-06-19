# Final Review — Estalatree (Phases 0–11)

**Date:** 2026-06-19 · **Reviewer:** assistant (review-only; no code changed)
**Scope:** end-to-end pass of the whole build through `18ba812` (Phase 11).
**Overall:** Strongly engineered. Every HIGH finding from the per-phase reviews is verified closed (consistent `phase-N-review fixes` commits). The core business cycle is money-correct and tested. Remaining work = Phase 11 secret handling, finish-or-fence multi-seller, and pre-production hardening.

---

## Verified closed (spot-checked in code)
| Finding | Evidence |
|---------|----------|
| Phase 9 H1 — double-charge | `checkout_token` stable per-intent (session/POST), not per-request random |
| Phase 10 H1 — Setting key mismatch | console + service now share `ACTIVATION_TOKEN_TTL_DAYS`, `MAINTENANCE_MODE="true/false"` — panic controls live |
| Phase 10 H2b — privilege | `manual_credit`/`refund_*` now `@superuser_required` |
| Phase 10 H3 — refund double-credit | `select_for_update` + deterministic `refund:{pk}` ref |
| Phase 10 M1/M4 | export uses `type`; audit `target_type="Customer"` matches |
| Phase 4 H1 — paid-but-undelivered | provisioning inside the debit atomic; `Grant.order`/`subscription` set |
| Phase 2/3 money | atomic+locked credit/debit, idempotent refs, webhook idempotency + safety net |

---

## Phase 11 — new findings

### HIGH
**H1. Secrets stored plaintext; `Secret` model unused.** `CredentialsProvisioner`/`ApiKeyProvisioner` store `password`/`api_key` directly in `Grant.payload` (plaintext JSON), sourced from `deliverable.config` (also plaintext). The Phase-1 `Secret` model (encrypted, shown-once) is unused; violates [15-provisioning §15.6](../15-provisioning-and-entitlements.md) and [23-configuration.md](../23-configuration.md). Same secret-trap pattern as Duitku→WA.
- **Action:** store these via the encrypted `Secret` model; never plaintext in `payload`/`config`.

### MEDIUM
**M1. Coupon `used_count` increment is non-atomic → `usage_limit` can be exceeded.** `update(used_count=coupon.used_count + 1)` uses an in-memory value (read-then-write); concurrent checkouts lose updates. `is_valid_for` checks the limit outside any lock.
- **Action:** `F("used_count") + 1`; ideally conditional `filter(used_count__lt=usage_limit).update(...)` + check rows-affected. Also verify redemption is recorded on the **top-up-and-buy** path, not only the balance-sufficient path.

**M2. Multi-seller is half-activated.** Seller dashboard is correctly scoped, but: (a) `store`/`block_add`/`block_remove` fall back to `StorePage.objects.first()` when the seller has no page → a seller can mutate another store's page; (b) the public storefront (`page`, `product_detail`) is still global (first StorePage, global slug) — no per-seller routing.
- **Action:** either keep single-merchant honestly, or finish per-seller isolation + public routing. Don't leave it half-way.

**M3. Broadcast sends WA synchronously in the request.** `broadcast` calls `send_wa()` in an inline loop — blocks the request, can time out, no async/dedup/rate-limit.
- **Action:** dispatch via `deliver_whatsapp.delay()` (Celery) + NotificationLog dedup (Phase 7 pattern).

### LOW
- Residual Phase 10 H2a: console still gated on `is_staff` (operators can technically reach `/admin/`) — use a dedicated Group to honor ADR-017.
- `account` deliverable type has no provisioner (KeyError → safe rollback now); expected (needs external I/O + async fulfillment — future).
- `seller_required` superuser auto-claims the first `SellerProfile`; no per-customer coupon limit; `_get_segment_customers` exclude-on-join may behave unexpectedly.

---

## Pre-production carryover (from cycle-completeness-eval, still open)
- Run the **live golden-path E2E** (Duitku sandbox): browse → SSO → top-up-and-buy → license key → activate → dashboard → renewal/reminder.
- Decisions: email verification required-vs-optional (currently `optional`); emoji in notification bodies (Phase 7 M3).
- Ensure money/concurrency tests run on **PostgreSQL** (not SQLite — `select_for_update` is a no-op there).
- Introduce a shared `get_secret("NAME")` helper (env/encrypted) to stop the recurring plaintext-secret pattern (H1 here, prior Duitku/WA).

---

## Readiness verdict
The system is on a production track: the hard parts (ledger integrity, licensing/activation, subscription lifecycle, idempotent webhooks, panic controls) are correct and tested, and review discipline has been excellent. Before calling it production-ready: fix Phase 11 H1 (secrets) and M1 (coupon race), resolve M2 (multi-seller scope), move broadcast async (M3), and complete the pre-production carryover (live E2E + the two pending decisions). The gaps are bounded and well-understood — no architectural rework required.
