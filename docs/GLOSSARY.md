# GLOSSARY — Domain Vocabulary

> English is the system standard ([CONVENTIONS.md](CONVENTIONS.md)). Use the **code identifier** column in code so naming stays consistent. Don't mix synonyms. Indonesian (and other) UI labels are handled later via Django i18n, not in this table.

## Core terms

| Term | Code identifier | Definition |
|------|-----------------|------------|
| Balance | `balance` (on `Wallet`) | Customer's prepaid money. Platform liability. |
| Wallet | `Wallet` | The balance holder, one per customer. |
| Ledger entry | `LedgerEntry` | Immutable record of each balance change. |
| Top-up | `TopUp` | A transaction adding balance via Duitku. |
| Top-up bonus | `bonus` | Extra promotional balance. |
| Product | `Product` | A digital item being sold. |
| Plan / Variant | `Plan` | A purchasable option of a product (price/interval/seat). |
| Order | `Order` | A purchase transaction (deducts balance). |
| Subscription | `Subscription` | Recurring access right. |
| Renewal | `renewal` | A subscription auto-deduct cycle. |
| Deliverable | `Deliverable` | What a plan provisions (declared spec). |
| Provisioner | `Provisioner` | Code that fulfills a deliverable type. |
| Grant | `Grant` | The issued artifact (license/credentials/etc.) + lifecycle. |
| Entitlement | `Entitlement` | A named feature capability gated by key. |
| License | `License` | Usage right + `key` (a `license_key` grant). |
| License key | `license_key` | Activation string, plain hash `XXXX-XXXX-XXXX`. |
| Installation / Device | `Installation` | A registered OSS product instance. |
| Fingerprint | `fingerprint` | Unique identity of an installation. |
| Seat limit | `seat_limit` | Max active installations per license. |
| Token | `token` | Short-lived signed activation token. |
| Grace period | `grace_period` / `grace_days` | Tolerance after due date / offline. |
| Lead (Contact) | `Lead` | A prospect from the WA "Contact" button. |
| Setting | `Setting` | Global key-value config. |
| Audit log | `AuditLog` | Immutable trail of sensitive actions. |
| Seller | `seller` / `SellerProfile` | Product owner (multi-tenant-ready). |

## Status values (TextChoices)

| Entity | Values |
|--------|--------|
| `Order` | `pending`, `paid`, `failed`, `refunded` |
| `TopUp` | `pending`, `paid`, `expired`, `failed` |
| `Subscription` | `active`, `grace`, `suspended`, `cancelled` |
| `License` | `active`, `suspended`, `revoked`, `expired` |
| `Installation` | `active`, `deactivated` |
| `Grant` | `active`, `suspended`, `revoked`, `expired` |
| `Lead` | `new`, `in_progress`, `closing`, `won`, `lost` |
| `Product.visibility` | `draft`, `unlisted`, `public` |
| `Product.type` | `free`, `one_time`, `recurring`, `contact` |
| `Plan.interval` | `none`, `monthly`, `yearly` |
| `LedgerEntry.type` | `topup`, `purchase`, `renewal`, `refund`, `adjustment`, `bonus` |
| `Deliverable.type` | `license_key`, `credentials`, `account`, `download`, `access_link`, `api_key`, `manual` |

## Roles
| Role | Identifier |
|------|------------|
| Platform owner | Superadmin |
| Operator / Staff | Admin |
| Buyer/user | Customer |
| Product instance (non-human) | Installation/Machine |
