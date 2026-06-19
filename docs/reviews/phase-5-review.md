# Phase 5 Review — Provisioning Layer + Activation API

**Date:** 2026-06-18 · **Reviewer:** assistant (review-only; no code changed)
**Commit reviewed:** `11224d3 Phase 5: Licensing provisioner + Activation API`
**Also confirmed:** `d86ff47` applied Phase 4 fixes (H1 provision-in-atomic, H2 Grant.order/subscription links, M1/M2/M3).
**Verdict:** Strong. HMAC token via `TimestampSigner` (no deps), TTL/grace/maintenance via `Setting` (zero-downtime), panic control, idempotent activate/deactivate, provisioner cascade with proper `Grant↔License` + `Grant.order/subscription` links, entitlements in response, thin API layer. Two HIGH (seat race, auth) + several MEDIUM.

## What's good (keep)
- Token bound to `license_key:fingerprint`, signed, reissued on validate (sliding); grace via second `max_age` check.
- Maintenance mode + global grace extension as Setting-driven panic controls.
- Idempotent activate (existing active fingerprint → fresh token, no new seat); idempotent deactivate.
- Provisioner cascade (suspend/resume/revoke/renew) updates both Grant and License; `Grant.order`/`subscription` set.

---

## HIGH

### H1. Seat-limit race condition (TOCTOU)
In `activate`, `if not license.seats_available` (count check) and `Installation.objects.create(...)` are **not** within a transaction holding a lock on the License. Two concurrent activations with different fingerprints on a 1-seat license can both pass the check and both create installations → seat limit exceeded. The `UniqueConstraint(license, fingerprint, active)` only prevents duplicate fingerprints, not seat-count overflow.
- **Action:** wrap the seat check + install create in `transaction.atomic()` + `select_for_update()` on the License row, and re-check the active seat count inside the lock.

### H2. Endpoints are `auth=None` — no product `secret`
[07-api.md](../07-api.md) and CONVENTIONS specify product auth = `license_key` + `secret` (`X-Estalatree-Secret` header). All three endpoints are open; the license key (shown/copied by users, leakable) is the only credential. Anyone who knows a license key + a fingerprint can `deactivate` a victim's seat (griefing); abuse surface rests on the key alone.
- **Action:** either implement the `X-Estalatree-Secret` product secret per spec, **or** consciously decide "the license key is the sole credential" (Keygen/Cryptlex style) and update [07-api.md](../07-api.md). Do not silently diverge from the spec.

---

## MEDIUM

### M1. `validate` doesn't require an active Installation for the fingerprint
`_verify_token` checks only signature (`license_key:fingerprint`) + timing, not that an active Installation still exists. After `deactivate` (or a reclaimed seat), the device keeps working until the token TTL expires (old token still passes). This weakens device-level seat enforcement and revocation granularity.
- **Action:** in `validate`, require an `ACTIVE` Installation for `(license, fingerprint)`; if none, return `invalid`/`deactivated` (force re-activate).

### M2. No AuditLog on sensitive operations
Provisioner `suspend/resume/revoke` and `deactivate` only `logger.info` + `.update()`. CONVENTIONS requires AuditLog for revoke/suspend.
- **Action:** write AuditLog on suspend/revoke (and optionally seat changes).

### M3. Rate limiting is non-atomic and per-process
`_check_rate_limit` does `cache.get` then `cache.set` (not atomic → undercounts concurrently); LocMemCache is per-process (won't span workers).
- **Action:** use atomic `cache.incr` (with TTL) / Redis in prod. Consider per-`(key+fingerprint)` limits — multi-seat licenses generate many heartbeats and may hit the 20/60s key limit.

### M4. Maintenance mode bypasses revocation even when the DB is reachable
`validate` under `MAINTENANCE_MODE=true` returns active for any key (including revoked/bogus) and issues a token. Intended as a panic control, but it's blunt.
- **Action:** document the tradeoff; if feasible, still honor revocation when the DB is reachable.

---

## LOW
- `_get_ip` trusts the first `X-Forwarded-For` hop (spoofable unless behind a trusted proxy) — only trust XFF behind a known proxy.
- Async-fulfillment (Phase 4 H1) isn't exercised yet because `license_key` provisioning is pure-DB; keep the design for `account`/`api_key` provisioners (Stage 2).
- `_get_entitlements` swallows broad `Exception` — acceptable, but log at debug.

---

## Suggested action mapping
| Item | When |
|------|------|
| H1 seat-race lock | Now (correctness) |
| H2 product secret vs spec | Now (decide + reconcile) |
| M1 validate requires active install | Now / Phase 6 |
| M2 AuditLog on suspend/revoke | Phase 6 (when cascade runs) |
| M3 atomic rate limit + Redis | Before prod |
| M4 maintenance scope | Phase 10 (panic controls UI) |
