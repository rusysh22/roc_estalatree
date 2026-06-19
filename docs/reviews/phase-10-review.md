# Phase 10 Review — Superadmin & Admin Tooling (Operator Console)

**Date:** 2026-06-19 · **Reviewer:** assistant (review-only; no code changed)
**State reviewed:** working tree (uncommitted) — `apps/console/` (views, decorators, templates).
**Verdict:** Comprehensive surface (setup checklist, cockpit + work queue, Customer 360, refund queue, manual credit, extend, CSV export, audit view, settings + panic). Money actions correctly go through `credit()` + AuditLog. But three HIGH issues (two make features silently non-functional, one is a money risk) and real bugs in export/audit.

## What's good (keep)
- Cockpit KPIs separate `balance_liability` (Sum wallet) from `revenue` — the right liability/revenue split.
- Unified work queue (leads + refunds + stuck top-ups + grace/suspended subs).
- Customer 360 aggregates orders/ledger/grants/subs/refunds/installations.
- Manual credit + refund go through `wallet.services.credit()` + `log_action`; reason required.
- `superuser_required` on setup + settings.

---

## HIGH

### H1. Setting key namespace mismatch — panic controls & tunables have no effect
`settings_view` writes keys/units that the services never read:
- `MAINTENANCE_MODE = "1"/"0"`, but Phase 5 checks `... == "true"` → maintenance never activates.
- UI `TOKEN_TTL_HOURS` / `GRACE_PERIOD_DAYS` / `GLOBAL_GRACE_EXTEND_HOURS` vs service `ACTIVATION_TOKEN_TTL_DAYS` / `ACTIVATION_GRACE_DAYS` / `GLOBAL_GRACE_EXTENSION_DAYS` (different names AND units).
- `MIN_TOPUP` exposed but not consumed anywhere (Phase 9 M2).

Editing TTL/grace/maintenance in the console changes nothing in the running system — the "zero-downtime tunable" premise breaks. Each phase invented its own key names.
- **Action:** a single canonical Setting-key registry (name + unit + default) shared by services and the console UI (ties to [../23-configuration.md](../23-configuration.md) "defaults in code, typed accessors").

### H2. RBAC diverges from ADR-017 and the roles doc
- Console is gated on `is_staff` — but `is_staff` is exactly Django's admin-access flag, so every Operator can reach `/admin/`, contradicting ADR-017 (Django Admin = Superadmin-only). Console access should be a dedicated Group/permission, not `is_staff`. (Work-queue items also deep-link to `/admin/...` for leads/stuck-topups — sending operators to the forbidden surface.)
- Money-sensitive `refund_approve` and `manual_credit` are `@staff_required`, but the roles doc says refund/balance-adjustment are Superadmin-only → should be `@superuser_required`.

### H3. Refund can double-credit
`refund_approve` has no `select_for_update` on the RefundRequest and uses a random ref `refund:{pk}:{uuid8}`, defeating `credit()` idempotency. Two concurrent/double-submitted approvals both pass `get_object_or_404(status=PENDING)` and both credit (different refs → two entries) → the customer is refunded twice.
- **Action:** deterministic ref `refund:{pk}` (so `credit()` dedupes) + `select_for_update` on the RefundRequest + re-check status inside the transaction. (Same class as the Phase 9 random `checkout_key`.)

---

## MEDIUM

### M1. `export_csv` ledger crashes
The ledger branch writes `e.entry_type`, but the model field is `type` → `AttributeError` on ledger export.

### M2. `extend_subscription` doesn't cascade resume
Extending moves the sub `SUSPENDED → ACTIVE` but never calls `provisioner.resume()` → Grant/License stay `SUSPENDED`, the product remains locked despite an "active" subscription. Route through `subscription_service`/the cascade.

### M3. Refund doesn't close the Order; revenue KPI is gross
`refund_approve` doesn't set `Order.status = REFUNDED`, so the order stays `PAID` and `revenue = Sum(PAID orders)` is overstated by refunded amounts (which are now liability again). Set `Order.REFUNDED` and/or net refunds out of revenue — this is the accuracy the liability/revenue split exists for.

### M4. Customer 360 audit panel is always empty
Filter `target_type="customer"` (lowercase) vs stored `target_type = type(target).__name__ = "Customer"` (capitalized) → never matches.

---

## LOW
- `manual_credit` / `extend_subscription` have no double-submit protection (random ref / no nonce) → double-click doubles the effect.
- Sequential PKs in URLs (`customer_pk`, `sub_pk`, refund `pk`) — `public_id` convention.
- `settings_view` cannot clear a setting to "" (only updates non-empty values).

---

## Suggested action mapping
| Item | When |
|------|------|
| H1 canonical Setting-key registry | Now (panic controls are non-functional) |
| H2 console access via Group; money actions superuser-only | Now |
| H3 deterministic refund ref + lock | Now (money) |
| M1 export `type` field fix | Now (crash) |
| M2 extend cascade resume | Now |
| M3 Order REFUNDED + net revenue | Now |
| M4 audit target_type case | Now |
| LOW | As convenient |
