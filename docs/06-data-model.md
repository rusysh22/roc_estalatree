# 06 — Data Model

> Conventions: every relevant model has `created_at`, `updated_at`. Business-strategic models have `seller` (FK, default = main seller) for multi-tenant readiness. **Money = whole rupiah integer** (`PositiveBigIntegerField`), not Decimal/float — see [CONVENTIONS.md](CONVENTIONS.md). IDs & statuses follow [CONVENTIONS.md](CONVENTIONS.md).
>
> The provisioning entities (Deliverable, Grant, Entitlement, Secret) are defined in [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md) and extend this model.

## Core entities

### accounts
- **Customer** — extends Django `User` (or `OneToOne` to User). Profile, WA contact.
- **SellerProfile** — (multi-ready) seller data. Default 1 row.

### wallet
- **Wallet** — `customer (1:1)`, `balance`.
- **LedgerEntry** *(immutable)* — `wallet`, `type` (`topup|purchase|renewal|refund|adjustment|bonus`), `amount` (+/−), `balance_after`, `ref` (unique, for idempotency), `note`, `created_at`.

### catalog
- **Product** — `seller`, `name`, `slug`, `type` (`free|one_time|recurring|contact`), `visibility` (`draft|unlisted|public`), `description`, `wa_number` (for contact).
- **Plan** — `product`, `name`, `price`, `interval` (`none|monthly|yearly`), `seat_limit`, `features (JSON)`, `is_active`.

### billing
- **Order** — `customer`, `plan`, `amount`, `status` (`pending|paid|failed|refunded`), `ledger_entry` (balance-deduction ref).
- **TopUp** — `customer`, `amount`, `bonus`, `gateway` (`duitku`), `gateway_ref`, `status` (`pending|paid|expired|failed`).
- **PaymentWebhook** — raw payload log + `idempotency_key` + `processed_at`.
- **Subscription** — `customer`, `plan`, `status` (`active|grace|suspended|cancelled`), `current_period_end`, `auto_renew`.

### licensing
- **License** — `key` (unique), `customer`, `plan`, `subscription (nullable)`, `status` (`active|suspended|revoked|expired`), `seat_limit`. (Specialization of a `license_key` Grant.)
- **Installation** — `license`, `fingerprint`, `name`, `status` (`active|deactivated`), `last_seen`, `activated_at`.

### crm
- **Lead** — `name`, `contact`, `product (nullable)`, `status` (`new|in_progress|closing|won|lost`), `notes`, `assigned_to`.

### core
- **AuditLog** *(immutable)* — `actor`, `action`, `target_type`, `target_id`, `meta (JSON)`, `created_at`.
- **Setting** — global key-value config (token TTL, grace days, min top-up, bonus rules, etc.).

## Relationships (summary)

```
Customer 1─1 Wallet 1─* LedgerEntry
Customer 1─* Order *─1 Plan *─1 Product
Customer 1─* Subscription *─1 Plan
Customer 1─* License *─1 Plan
License  1─* Installation
Customer 1─* TopUp
Product  1─* Plan
```

## Integrity rules

- `Wallet.balance` always equals `SUM(LedgerEntry.amount)` for that wallet. Invariant test mandatory.
- `LedgerEntry` & `AuditLog` are **never** updated/deleted (enforced in the service layer + admin permission overrides).
- Active `Installation`s per `License` must not exceed `License.seat_limit`.
