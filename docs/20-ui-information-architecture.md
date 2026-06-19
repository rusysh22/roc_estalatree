# 20 — UI & Information Architecture

> Estalatree has **three distinct surfaces**. This doc defines navigation, the admin-UI approach, and the link-in-bio storefront model. Reference point: the Lynk.id creator dashboard (mapping at the end).

## 20.1 The four surfaces (separate URLs)

| Surface | URL | Who | Tech |
|---------|-----|-----|------|
| **Django Admin** | `/admin/` | **Superadmin only** | Django Admin |
| **Operator Console** | `/console/` | Admin/Operator (+ Superadmin) | Custom HTMX |
| **Customer Dashboard** | `/dashboard/` | Customer | Custom HTMX |
| **Public Storefront** | `/`, `/<slug>` | Visitors / buyers | Custom HTMX, **link-in-bio page** |

### Identity & access (one account, multiple roles)
- A single **`User`** can hold multiple capabilities at once — e.g. someone who is an **Operator/Seller** *and* a **Customer** (important for the multi-seller future, where a seller may also buy).
- Surfaces are gated by **capability**, not by separate accounts:
  - `is_superuser` → Django Admin + Operator Console.
  - operator group/permission → Operator Console only.
  - has `CustomerProfile` (Wallet) → Customer Dashboard.
- Operators **never** access Django Admin (least privilege); raw DB power and dangerous ops are Superadmin-only.

---

## 20.2 Admin surfaces (split)

**Decision:** the daily admin work happens in a **custom HTMX Operator Console** (so it looks like a designed product, à la Lynk.id), available to Operators **and** Superadmin. **Django Admin is Superadmin-only** and handles deep CRUD/back-office, RBAC, gateway config, and dangerous data ops — Operators never see it.

**Operator Console** (`/console/`) — custom HTMX, designed, daily-use:
- **Home** — KPI cards: Balance Float (liability) · Revenue recognized · Active Licenses · Failed Renewals · Today's Top-ups · Orders · Leads. Quick actions: "New Product", "New Voucher".
- **Storefront** — edit the link-in-bio page + Appearance/theme.
- **Products** — Products, Plans, Deliverables, Entitlements.
- **Orders** · **Customers (Customer 360)** · **Licenses & Devices** · **Subscriptions** · **Top-ups & Ledger** · **Leads (Contact)**.
- **Marketing** — Vouchers, WA/Email broadcast *(Stage 2)*.
- **Reports / Reconciliation** *(Stage 1)* · **System Health** *(Stage 1)* · **Audit Log** · **Settings** (Duitku, WA, global tunables).

**Django Admin** (`/admin/`, **Superadmin only**) — back-office / data depth:
- Raw CRUD on every model, bulk edits, permissions/Groups (RBAC), one-off data fixes, immutable-model inspection (LedgerEntry, AuditLog read-only).

> Split rule: anything done **daily** or needing **at-a-glance metrics** → Operator Console. **Occasional deep data work / dangerous ops** → Django Admin (Superadmin only).

---

## 20.3 Customer Dashboard

- **Home** — balance + **renewal forecast** ("next renewal Rp X on Y; balance covers N months") + active subscriptions + quick links.
- **Balance / Top-up** — top up + ledger history.
- **My Products** — purchased items + downloads.
- **License Keys** — copy key (1-click) + activation guide.
- **Devices / Installations** — seat usage (e.g. 2/3), name/remove devices.
- **Subscriptions** — status, renewal date, **auto-renew toggle**, grace-period banner.
- **Invoices / Transactions** — PDF invoices, top-up receipts.
- **Profile & Security** — SSO/Google, 2FA, notification contacts (WA/email).
- **Support** — tickets / WA.

---

## 20.4 Public Storefront — link-in-bio model

**Decision:** Lynk.id-style **shareable store page** (e.g. `estalatree.id/<slug>`), composed of **Blocks**, with an **Appearance/theme**.

- **StorePage** — the public, shareable page (one per seller; single-merchant = one page now).
- **Block** — an ordered content unit on the page. Types: `product`, `link`, `text/blog`, `course`, `media_kit`, `heading`. (Start with `product` + `link`; add others as needed.)
- **Appearance** — theme/colors/avatar/cover (basic in MVP, richer themes in Growth).
- **Product page** — detail + plan comparison (features = Entitlements) + checkout (pay from balance) or **top-up-and-buy**.
- **Contact button** (WA) for `contact`-type products → creates a Lead.

### New entities (extend [06-data-model.md](06-data-model.md))
- **StorePage** — `seller`, `slug`, `title`, `theme (JSON)`, `is_published`.
- **Block** — `store_page`, `type`, `position`, `config (JSON)`, `product (nullable)`, `is_visible`.

---

## 20.5 Lynk.id → Estalatree mapping (reference)

| Lynk.id | Estalatree | Action |
|---|---|---|
| Home (KPI + quick create) | Owner Cockpit Home | Adopt pattern, our metrics |
| My Lynk (link-in-bio) | StorePage (Blocks) | Adapt |
| Appearance | Storefront theme | Adapt (later) |
| Statistics | Analytics | Keep |
| Orders | Orders | Keep |
| My Purchase | Customer Dashboard | Becomes its own surface |
| Vouchers | Coupon/promo engine | Keep (Stage 2) |
| Affiliates / Email / WA Blast / Automate | Marketing tools | Stage 2–3 |
| Earnings / Payout / PayMe | Your revenue (not payout) | Re-frame; payout only when multi-seller |
| Upgrade to PRO | — | Drop |
| Add Link / Blog / Course / Media Kit | Block types | Scope per need; start with product + link |
| *(none)* | Balance/Top-up, License Keys, Devices, Subscriptions, Activation health | **New — Estalatree core** |

---

## 20.6 Stage alignment
- **MVP (Stage 0):** cockpit Home + Products/Orders/Customers + Customer Dashboard + basic StorePage (product/link blocks) + checkout.
- **Stage 1:** Reconciliation, System Health, Customer 360 depth, panic controls.
- **Stage 2+:** Appearance themes, Vouchers, broadcast, affiliates, more block types.
