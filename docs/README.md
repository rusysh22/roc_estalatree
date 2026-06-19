# Estalatree — Product & Technical Documentation

A digital-product selling platform (lynk.id-style) whose differentiator is **token-based licensing & activation** for open-source products, powered by a **Sumopod-style prepaid balance (top-up)** system.

> **Language standard:** English (code, docs, base UI). See [CONVENTIONS.md](CONVENTIONS.md).
> **New here (AI agent / dev):** read this → [13-agent-handoff.md](13-agent-handoff.md) → [12-build-plan.md](12-build-plan.md). Current progress: [STATUS.md](STATUS.md).

---

## Document Map

| # | Document | Contents |
|---|----------|----------|
| — | [README.md](README.md) | This index |
| — | [STATUS.md](STATUS.md) | Live progress board |
| — | [CONVENTIONS.md](CONVENTIONS.md) | **Engineering standards** (language, money, IDs, status, errors, tests) |
| — | [GLOSSARY.md](GLOSSARY.md) | Domain vocabulary & status values |
| — | [DECISIONS.md](DECISIONS.md) | Architecture decision log (ADR-lite) |
| 01 | [01-overview.md](01-overview.md) | Vision, principles, goals/non-goals |
| 02 | [02-roles.md](02-roles.md) | Personas & RBAC |
| 03 | [03-core-concepts.md](03-core-concepts.md) | **Wallet/balance + token engine** (the spine) |
| 04 | [04-products-pricing.md](04-products-pricing.md) | Product types, plans, delivery |
| 05 | [05-flows.md](05-flows.md) | End-to-end flows |
| 06 | [06-data-model.md](06-data-model.md) | Entities & relationships |
| 07 | [07-api.md](07-api.md) | Activation API spec |
| 08 | [08-integrations.md](08-integrations.md) | Duitku, WhatsApp, Email, Notifications |
| 09 | [09-features.md](09-features.md) | Features per module |
| 10 | [10-non-functional.md](10-non-functional.md) | Security, audit, jobs, quality |
| 11 | [11-tech-stack.md](11-tech-stack.md) | Stack & project structure |
| 12 | [12-build-plan.md](12-build-plan.md) | **Build order (backend-first) + phase checklists** |
| 13 | [13-agent-handoff.md](13-agent-handoff.md) | **Continuity guide for successor agents** |
| 14 | [14-state-machines.md](14-state-machines.md) | Status transitions |
| 15 | [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md) | **Generalized fulfillment** (sell more than licenses) + entitlements |
| 16 | [16-auth-and-sso.md](16-auth-and-sso.md) | Authentication & SSO (Google, etc.) |
| 17 | [17-product-packaging.md](17-product-packaging.md) | Product/plan/add-on/bundle design |
| 18 | [18-product-evolution.md](18-product-evolution.md) | Product maturity stages (MVP → platform) |
| 19 | [19-extensibility.md](19-extensibility.md) | How to add features/patches cleanly |
| 20 | [20-ui-information-architecture.md](20-ui-information-architecture.md) | UI/IA — 3 surfaces, hybrid admin, link-in-bio storefront |
| 21 | [21-user-journeys.md](21-user-journeys.md) | **A–Z connected journeys per persona** + friction-reducers |
| 22 | [22-feature-catalog.md](22-feature-catalog.md) | Lynk.id PRO features → Estalatree all-access (no owner tiering) |
| 23 | [23-configuration.md](23-configuration.md) | Config management — 3 tiers (.env vs DB Setting vs per-record) |

---

## 30-second summary

- **Stack:** Django + Django Ninja + PostgreSQL + HTMX + Tailwind.
- **Business model:** customers top up a wallet (via Duitku) → buy/subscribe → balance is deducted. Recurring = balance auto-deduct (not card auto-debit).
- **Differentiator:** what's sold is an Entitlement fulfilled by a pluggable Provisioner producing a Grant — license key, generated credentials, account, download, or API key.
- **Tenancy:** single-merchant, multi-tenant-ready (`seller` modeled, not activated).
- **Money principle:** customer balance = **liability**; ledger **immutable & double-entry-style** from day one.

## Status

Phase: **Design (pre-implementation)**. See [STATUS.md](STATUS.md).
