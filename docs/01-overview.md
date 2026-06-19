# 01 — Overview

## Vision

**Estalatree** is a digital-product selling platform whose key differentiator is **token-based licensing & activation for open-source products**, powered by a **Sumopod-style prepaid balance (top-up)** system.

Customers top up a balance, then buy or subscribe to products. OSS products (desktop, CLI, self-hosted web apps) "phone home" to the Estalatree API for online token validation — while the subscription is active the product runs; when it lapses the product locks itself.

## Why a balance model?

Indonesian payment gateways (Duitku) **do not support subscription auto-debit**. With a prepaid balance:

- **Recurring = auto-deduct from balance** (as long as funds suffice, renewal is automatic).
- Duitku is used **only** at top-up time.
- It fits Indonesian payment culture and infrastructure.

## Design Principles

1. **Dynamic & not complicated** — one codebase, lean on Django Admin as much as possible.
2. **Customer balance = liability** — immutable ledger and clean accounting from day one. Money becomes "platform revenue" only when balance is spent on a product.
3. **Single-merchant, multi-tenant-ready** — you are the only seller; the schema prepares a `seller` concept so it can open to other sellers without a major rewrite.
4. **Stable & standard** — service-layer pattern, atomic money transactions, mandatory tests on money paths, env-based config, always migrate.

## Goals (MVP)

- Customer: register, top up via Duitku, buy/subscribe, receive license key.
- OSS products: activate & validate tokens via API.
- Recurring via balance auto-deduct + WA/email reminders.
- Product types: Free, One-time, Recurring, Contact (WA).
- Superadmin & Admin: manage products, licenses, customers, transactions, leads.
- Immutable, audited balance ledger.

## Non-Goals (for now)

- Full multi-seller marketplace (payouts, commissions) — modeled in the schema, not implemented.
- Credit-card auto-debit.
- Native mobile app.
- Affiliate/reseller program.
