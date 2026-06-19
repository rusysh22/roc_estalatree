# Phase 1 Review — Domain Models

**Date:** 2026-06-18 · **Reviewer:** assistant (review-only; no code changed)
**Commit reviewed:** `7ef3428 phase1: domain models`
**Verdict:** Strong, faithful to docs & ADRs. Items below are best-practice recommendations, prioritized. None block correctness today; HIGH items are cheapest to fix now.

## What's good (keep)
- Immutable LedgerEntry/AuditLog enforced in Django Admin (`has_add/change/delete_permission=False`, readonly fields).
- `ref` idempotency key (unique) on LedgerEntry; money as integer IDR.
- Order/TopUp price **snapshot** (`amount`) and prefixed `public_id`.
- Installation `UniqueConstraint(license, fingerprint)` where `status=active`.
- Crockford Base32 charset correct (no I L O U); license key 14-char `XXXX-XXXX-XXXX`.
- Provisioner registry via `Protocol`; domain-event + audit scaffolding; `SellerScopedModel` ready.

---

## HIGH — do now while cheapest

### H1. Adopt a custom User model
Currently default `django.contrib.auth.User` + `Customer` OneToOne; no `AUTH_USER_MODEL`.
- Django's official guidance: **always start with a custom user model**; switching after data exists is very painful. You are at the cheapest moment (only `0001` migrations, no data).
- Auth is allauth + Google SSO + email login (no usernames) → use a custom User with **email as identifier**.
- **Action:** decide before further phases. If adopted, reset initial migrations accordingly.

### H2. Enforce immutability at the model level (not just Admin)
`LedgerEntry` and `AuditLog` are append-only, but services/shell/scripts can still `.save()`/`.delete()`.
- **Action:** override `save()` to raise if `pk` is already set (block updates) and `delete()` to raise. Admin perms are not sufficient for a money system.

### H3. Guarantee Wallet creation with Customer
`Wallet` is `OneToOne` to `Customer`, but nothing guarantees existence → `customer.wallet` can raise `RelatedObjectDoesNotExist` at checkout/top-up.
- **Action (Phase 2):** create the Wallet atomically when the Customer is created (service or `post_save` signal).

### H4. Dispatch domain events via `transaction.on_commit`
`emit()` runs handlers synchronously inline and swallows exceptions.
- Risk: handlers fire on state that may be rolled back.
- **Action:** dispatch via `transaction.on_commit`; codify the rule **events are for side-effects only, never money correctness** (money steps stay inside the service transaction, not in best-effort handlers).

---

## MEDIUM

### M1. `Plan.features` (JSON) overlaps `Entitlement`
Two places describe capabilities. Per ADR-010, Entitlements are the gating source of truth.
- **Action:** define `features` as **display-only** (marketing bullets) and `Entitlement` as **enforced gating**; document or rename to prevent drift.

### M2. Multi-seller slug uniqueness
`Product.slug` (and `SellerProfile.slug`) are globally unique; under multi-seller (ADR-005) sellers will collide.
- **Action (at multi-seller activation):** `UniqueConstraint(seller, slug)` for Product. Note now so it isn't forgotten.

### M3. Collision retry for generated IDs
`public_id` and license key have huge spaces but no retry on the rare `IntegrityError`.
- **Action:** small retry loop on `IntegrityError` in generation/save.

---

## LOW / deferred

- **L1.** Redundant explicit `Index` on `unique=True` fields (`LedgerEntry.ref`, `License.key`) — `unique` already indexes; drop the explicit ones.
- **L2.** `Setting.get()` is string-only, uncached — when consumed (Phase 3+), add typed/cached accessors + defaults-in-code registry per [../23-configuration.md](../23-configuration.md).
- **L3.** `Grant.has_entitlement`/`get_entitlements` can N+1 in loops — `prefetch_related` where used in the activation API (Phase 5).
- **L4.** `storefront` StorePage/Block models are empty — confirm intentional deferral to Phase 9 (consistent with the build plan); not a defect.
- **L5.** `TIME_ZONE="Asia/Jakarta"` + `USE_TZ=True` is fine (DB stores UTC). Be explicit about WIB day-boundaries in renewal date math (Phase 6).

---

## Suggested action mapping
| Item | When |
|------|------|
| H1 custom User | **Now** (before Phase 2) |
| H2 model immutability | Now / Phase 2 |
| H3 Wallet creation | Phase 2 |
| H4 events on_commit | Phase 2 (before events are relied on) |
| M1 features vs entitlements | Phase 4 |
| M2 slug per seller | Multi-seller (Stage 3) |
| M3 collision retry | Phase 2 |
| L1–L5 | As the relevant phase lands |
