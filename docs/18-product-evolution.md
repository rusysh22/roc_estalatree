# 18 — Product Evolution (Initial → Mature)

> **Product** maturity stages (the *what/why*), distinct from [12-build-plan.md](12-build-plan.md) (the *engineering how/order*). Each stage is shippable and builds on the last. Core first; everything else slots in via [19-extensibility.md](19-extensibility.md).

## Stage 0 — Core MVP ("sell & activate")
**Goal:** a customer can fund a wallet, buy, and activate a product.
- Single seller. `license_key` products only.
- Wallet top-up (Duitku) + immutable ledger.
- Checkout (deduct balance) → Grant → License Key.
- Activation API (activate / validate / deactivate).
- Recurring via auto-deduct + grace/suspend.
- Minimal storefront + customer dashboard + Django Admin.
- Email/WA notifications (core events).

➡ Maps to build-plan Phases 0–9 (MVP slice 0–6).

## Stage 1 — Operability & Trust ("safe to run daily")
**Goal:** you can operate it without fear.
- **Financial reconciliation** (balance float vs revenue; Duitku settlement match).
- **Panic controls** for activation API (global grace extend / maintenance) so a server outage never bricks customers.
- **System Health**: failed-webhook & failed-job queues + retry.
- **Customer 360 / timeline** for support; license ops (resend, extend, transfer, revoke, reset seat).
- Invoices + tax identity (PPN/company info).
- Audit log surfacing; 2FA for admins.

## Stage 2 — Growth ("more to sell, easier to buy")
**Goal:** raise conversion and expand offerings.
- **More Deliverable types**: `credentials` (generate password), `account`, `download`, `api_key` provisioners.
- **Entitlements console** for feature gating.
- **Promo engine**: coupons, top-up bonus tiers; **Add-ons** & **Bundles**.
- **Google SSO** + richer onboarding.
- **Analytics**: LTV, retention/cohort, churn drivers.
- Self-serve refund/cancel requests; in-dashboard support tickets.

## Stage 3 — Scale / Platform ("open it up")
**Goal:** become a platform, not just a store.
- **Activate multi-seller** (the dormant `seller` concept): seller onboarding, scoped data, payouts/commission.
- Public seller/developer **API** + webhooks.
- Advanced licensing options (offline signed machine files, floating licenses).
- More SSO providers; optional enterprise OIDC/SAML.
- Referral/affiliate program.

---

### Guiding rule
Never let a later stage force a Stage-0 rewrite. That is enforced structurally by [19-extensibility.md](19-extensibility.md): modular apps, domain events, provisioner registry, entitlement-driven features, externalized config.
