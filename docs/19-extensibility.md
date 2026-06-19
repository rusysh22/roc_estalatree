# 19 — Extensibility (Core Now, Patches Later — Cleanly)

> This doc exists so that adding features/fixes later is *enak* (pleasant), not surgery on the core. These are structural guarantees, not aspirations.

## 19.1 Modular apps, thin contracts
- Each Django app owns one domain ([11-tech-stack.md](11-tech-stack.md)).
- Apps talk through **service functions**, never deep cross-app model imports.
- Dependency direction is one-way: `core → accounts → wallet → catalog → billing → licensing/provisioning → notifications → crm`.

## 19.2 Domain events (the decoupler)
Core operations **emit events**; new features **subscribe** without touching core.

Events (initial): `topup_credited`, `order_paid`, `grant_provisioned`, `subscription_renewed`, `subscription_suspended`, `grant_revoked`, `low_balance`.

Subscribers: notifications, analytics, provisioners, audit. Adding analytics later = add a subscriber, change nothing in billing.

> Implementation: Django signals or a small in-process event bus dispatched to async jobs.

## 19.3 Provisioner registry (plugin pattern)
New things to sell = new **Provisioner** registered in a registry ([15](15-provisioning-and-entitlements.md)). Checkout/billing/subscription code is type-agnostic — it calls the registry.

## 19.4 Entitlement-driven features
Gate features by **entitlement key**, never by plan name. New feature = new entitlement key + a check. No migration, no plan-by-plan branching.

## 19.5 Externalized configuration
Tunables live in `Setting` (token TTL, grace days, top-up bonus rules, min top-up, platform fee), editable by Superadmin — no deploy to change behavior.

## 19.6 Channel & gateway abstractions
- **Notifications** behind a channel interface (WA / email / push) — add a channel without touching callers.
- **Payment gateway** behind an interface — Duitku today; another gateway later implements the same port.

## 19.7 Versioned, stable boundaries
- Public/product-facing API is versioned (`/v1`). Breaking changes → `/v2`, old kept.
- Service-layer function signatures are the internal contract; keep them stable.

## 19.8 Rollout safety
- Feature flags (release/ops/permission) for shipping incrementally.
- Anti-corruption: external systems (Duitku, WA gateway, provisioned apps) are wrapped in adapters, never leak their shapes into the domain.

## Checklist for any new feature
- [ ] Lives in the right app (or a new one) with a clear service API.
- [ ] Reacts to a domain event rather than editing core flow, where possible.
- [ ] New "thing to sell" → a Provisioner, not a special case in checkout.
- [ ] New feature gate → an Entitlement, not a plan-name check.
- [ ] New tunable → a `Setting`, not a constant.
- [ ] External dependency → wrapped in an adapter.
