# 09 — Features per Module

> Persona-driven feature additions (Customer 360, financial reconciliation, panic controls, balance forecast/alerts, etc.) are tracked for folding in — see [STATUS.md](STATUS.md). The list below is the baseline.

## 9.1 Superadmin
- **Dashboard**: balance float (liability) · top-ups today · revenue recognized · active licenses · failed renewals · churn · incoming leads.
- **RBAC**: manage admins & permissions (Django Groups).
- **Duitku config** (sandbox/prod, API key, merchant code).
- **Global settings**: token TTL, grace period length, top-up bonus rules, minimum top-up, notification templates.
- **Audit log** (who changed what) — read-only.
- **Refund approval** & large adjustments.
- **Abuse monitoring**: one license on too many machines, chargebacks, anomalies.
- **Financial reports** & export (top-ups, revenue, liability).
- **Maintenance mode**, broadcast/announcement.

## 9.2 Admin / Operator
- Manage **Products & Plans/Variants**, catalog, visibility.
- **CRM-lite "Contact" leads**: lead → status (`new/in_progress/closing/won/lost`) → WA follow-up → convert to a manual invoice/order.
- **Support**: view customer, reset device, manual renewal, manual top-up/adjustment (reason required + audited).
- Manage licenses & installations.

## 9.3 Customer (Dashboard — HTMX)
- **Balance** + top-up button + balance history (ledger).
- **My Products** + downloads.
- **License Keys**.
- **Installations / Devices** (view & remove a device).
- **Subscriptions** + renewal date + **auto-renew toggle**.
- **Transaction history & invoices** (PDF).
- Support/contact.

## 9.4 Storefront (Public)
- Catalog, product page, checkout (pay from balance).
- **Contact** button (WA) for `contact`-type products.
- (Optional UX) **top-up-and-buy**: if balance is short, combine top-up + purchase in one flow.
