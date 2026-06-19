# 02 — Roles & Personas

| Role | Who | Main access |
|------|-----|-------------|
| **Superadmin** | Platform owner (you) | Everything. Revenue, balance liability, manage admins (RBAC), gateway config, global settings, audit log, refund approval. |
| **Admin / Operator** | Staff | Manage products & plans, follow up "Contact" leads, customer support, manual top-up/adjustment (audited). |
| **Customer** | Buyer & user | Top up, buy, manage licenses & devices, history & invoices, auto-renew. |
| **Installation / Machine** | OSS product instance (non-human) | Activation & heartbeat via API token. |

## RBAC Notes

- **Surfaces are separate** (see [20-ui-information-architecture.md](20-ui-information-architecture.md)): `/admin/` (Django Admin), `/console/` (Operator Console), `/dashboard/` (Customer), storefront.
- **Django Admin is Superadmin-only.** Admin/Operator work in the **Operator Console** (custom HTMX) — they never access Django Admin (least privilege).
- Sensitive actions (refund, balance adjustment, gateway config changes) are **Superadmin-only** and always recorded in the **AuditLog**.
- **One account, multiple roles.** A single `User` can be Operator/Seller *and* Customer at once; access is gated by capability, not separate accounts (matters for multi-seller).
- **Customers** use the Customer Dashboard (HTMX), never Django Admin.
- An **Installation** is not a user; it authenticates via **license key + secret** at the API, not a login session.

## Multi-tenant-ready

A `seller` concept is embedded in strategic models (see [06-data-model.md](06-data-model.md)). Currently all data belongs to **one default seller**. When the marketplace opens, the **Seller** role becomes an Admin subtype that only sees its own data.
