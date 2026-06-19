# Phase 6 Review — Subscriptions & Background Jobs

**Date:** 2026-06-18 · **Reviewer:** assistant (review-only; no code changed)
**Commit reviewed:** `43334e7 Phase 6: Subscription renewal + background jobs`
**Also confirmed:** `b0fa5e6` applied Phase 5 fixes (seat TOCTOU lock, auth, AuditLog, atomic rate limit).
**Verdict:** High quality. Correct renewal idempotency (`renewal:{sub}:{period_end_ts}`, fast-path + in-lock re-check), `select_for_update`, debit→extend→cascade all inside one atomic, `InsufficientBalance` rolls the order back, grace→suspend via conditional update (idempotent), and **timezone handled correctly** (datetime-based periods in UTC — WIB day-boundary trap avoided). Findings are about state-machine completeness, not data corruption.

## What's good (keep)
- Renewal idempotency tied to (sub, period_end); concurrency-safe via lock + re-check.
- Money all via `debit()`; failed charge rolls back the Order (no orphan PENDING).
- Cascade renew/suspend uses `Grant.subscription` link (Phase 4 H2); re-activates SUSPENDED grants on renew.
- Conditional-update GRACE transition (idempotent) + AuditLog on each state change.
- Celery tasks: `acks_late`, retries; jobs separated (renew / expire-grace / poll-topups).

---

## MEDIUM

### M1. SUSPENDED subscriptions are not reactivated on top-up
`try_renew_grace_subscriptions` targets only `GRACE` status. [14-state-machines.md](../14-state-machines.md) and journey step 8 require `suspended ──top-up & renew──> active`. A customer who lapsed past grace into `SUSPENDED`, then tops up, stays suspended (product stays locked) — no job reactivates them. `renew_subscription` itself can reactivate (cascade sets Grant+License ACTIVE); just widen the `try_renew` filter to include `SUSPENDED`.
- **Action:** include `SUSPENDED` (with `auto_renew=True`) in the top-up reactivation path.

### M2. `auto_renew=False` subscriptions never expire
`process_due_renewals` filters `auto_renew=True`; `process_grace_expirations` only handles `GRACE`. An `ACTIVE` sub with `auto_renew=False` past `current_period_end` stays `ACTIVE` forever — License stays ACTIVE, product keeps working past the paid period (revenue leak). The state machine says `active ──auto_renew off & period ends──> cancelled`.
- **Action:** add handling for `ACTIVE` + `auto_renew=False` + period elapsed → suspend (cascade) then `CANCELLED`/`EXPIRED`.

### M3. No domain events emitted
Renewal/grace/suspend only `log_action`, no `emit()`. Phase 7 (notifications) and the H-3/H-1 reminders (journey step 8) depend on these signals.
- **Action:** emit `subscription.renewed` / `subscription.graced` / `subscription.suspended` / `subscription.reactivated` now (handlers land in Phase 7). Also note: **no source yet emits "upcoming renewal"** — Phase 7 needs a job to emit H-3/H-1 reminders from `current_period_end`.

---

## LOW
- Verify `try_renew_grace_subscriptions` runs after the top-up credit is available (within the same txn the balance is already written — likely fine; confirm).
- A persistently failing sub is retried every run with no backoff/alert — surface repeated failures to System Health (Phase 10).
- `actor=None` on job AuditLog entries is correct (system actions).

---

## Suggested action mapping
| Item | When |
|------|------|
| M1 reactivate SUSPENDED on top-up | Now (completes journey step 8) |
| M2 expire auto_renew=False subs | Now (revenue leak + state machine) |
| M3 emit subscription events + upcoming-renewal source | Phase 7 |
| LOW | Phase 7 / Phase 10 |
