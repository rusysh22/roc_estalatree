# 12 — Build Plan (Build Order)

**Philosophy:** **Backend-first, foundation-first.** Build from the core that everything else depends on (data + money + provisioning) up to the UI. Each phase has a **Definition of Done (DoD)** and **mandatory tests**. Don't skip phases — upper modules depend on lower ones.

> How to use: work phases in order. Check off tasks in [STATUS.md](STATUS.md) once DoD is met + tests green + committed. One phase ≈ one or a few handoff-able PRs.
>
> **Reconciled 2026-06-18:** Folded journey requirements ([21](21-user-journeys.md)), provisioning model ([15](15-provisioning-and-entitlements.md)), and persona features ([09](09-features.md)) into each phase. Phase 5 is now "licensing as the `license_key` provisioner" inside the general provisioning layer (not a separate licensing system).

---

## Phase 0 — Setup, Standards & Stability Layer
**Goal:** skeleton runs + the guardrails that make vibe-coding safe (see [CONVENTIONS.md](CONVENTIONS.md) → CI & Quality Gates).
- [ ] Init Django project (structure in [11-tech-stack.md](11-tech-stack.md)).
- [ ] Settings `base/dev/prod` + django-environ + `.env.example`.
- [ ] PostgreSQL connection; **Docker Compose** (db+redis) for dev/prod parity.
- [ ] **Dependency management with uv** + committed **lockfile** (pinned versions).
- [ ] Tooling: black, ruff, isort, pytest-django, factory_boy, **pre-commit incl. secret scanning** (gitleaks/detect-secrets).
- [ ] **CI (GitHub Actions)**: lint + tests + `makemigrations --check` + `pip-audit`.
- [ ] **Sentry + structured logging** scaffold.
- [ ] **Heroicons SVG** set wired (inline/sprite), base Tailwind layout — no emoji.
- [ ] Empty app skeleton: accounts, wallet, catalog, billing, provisioning, licensing, storefront, console, dashboard, crm, notifications, core.
- [ ] **Golden-path smoke test stub** (to be filled as phases land): top-up → buy → activate → renew.
**DoD:** `manage.py check` & `pytest` run in CI; lint + secret scan green; server boots; lockfile committed.

## Phase 1 — Domain Models (Spine)
**Goal:** all entities + migrations + basic Django Admin.
- [ ] Abstract base model (`created_at/updated_at`, `seller` mixin) in `core`.
- [ ] All app models per [06-data-model.md](06-data-model.md):
  - `accounts`: `Customer`, `SellerProfile`.
  - `wallet`: `Wallet`, `LedgerEntry` (immutable; block update/delete in Admin).
  - `catalog`: `Product`, `Plan`.
  - `billing`: `Order`, `TopUp`, `PaymentWebhook`, `Subscription`.
  - `licensing`: `License`, `Installation` (specialization of `license_key` Grant — see provisioning).
  - `crm`: `Lead`.
- [ ] **Provisioning entities** per [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md):
  - `Deliverable` (`plan`, `type`, `config JSON`).
  - `Grant` (base: `customer`, `subscription nullable`, `type`, `status`, `meta JSON`, `valid_until`).
  - `Entitlement` (`plan`, `key`, `value`) — feature gating, never branch on plan name.
  - `Secret` (encrypted credential store for `credentials`/`api_key` grants).
  - Provisioner **registry** scaffold (`provisioning/registry.py`): `register()` + `get()`.
- [ ] Initial migrations + register all models in Django Admin.
- [ ] `Setting` & `AuditLog` (immutable) + audit helper. Domain-event scaffold (`core/events.py`).
**DoD:** clean migrations; all models visible & creatable in Django Admin; provisioner registry importable.
**Depends:** Phase 0.

## Phase 2 — Wallet & Ledger (MONEY — most critical)
**Goal:** balance can be trusted.
- [ ] `wallet/services.py`: `credit()`, `debit()` — atomic, `select_for_update`, idempotent `ref`, reject negative balance, write `balance_after`.
- [ ] Immutable LedgerEntry (block update/delete).
- [ ] **Tests:** invariant `balance == SUM(ledger)`, idempotency, concurrency, reject overdraw.
**DoD:** all money tests green; no balance mutation outside the service layer.
**Depends:** Phase 1.

## Phase 3 — Top-up (Duitku)
**Goal:** money can enter as balance; webhook failures never strand a customer.
- [ ] Duitku client (sandbox) + invoice creation.
- [ ] TopUp model/flow `pending → paid`.
- [ ] **Webhook**: verify signature + idempotent (`PaymentWebhook`) → `credit()` (+bonus).
- [ ] **Webhook safety net** (journey step 4): if webhook lags, TopUp stays `pending`; background retry job re-checks with Duitku; System Health queue surfaces failed/stuck webhooks to Superadmin for manual retry. Customer sees "payment pending" + "check status" button (never stranded).
- [ ] **Tests:** webhook success/duplicate/invalid-signature/stuck-pending.
**DoD:** a sandbox top-up increases balance via the ledger, with no double-credit; a missed webhook is retried and surfaced.
**Depends:** Phase 2.

## Phase 4 — Catalog & Checkout
**Goal:** customer can buy; a grant is issued; first-time buyers aren't blocked by a separate top-up wall.
- [ ] CRUD Product, Plan, Deliverable, Entitlement (Admin).
- [ ] Checkout service: `debit()` balance → Order → run **provisioner(s)** → issue **Grant(s)** per type (free/one_time/recurring/contact).
- [ ] **Top-up-and-buy** (journey step 3, ADR-015): if balance < plan price at checkout, checkout service creates a Duitku invoice for the exact/suggested delta **and** atomically completes the purchase on webhook receipt — one transaction, not two flows.
- [ ] **Inline Google SSO at checkout** (ADR-016): account created or retrieved via allauth Google OAuth during buy; no separate signup wall. Service must tolerate unauthenticated-to-authenticated transition mid-checkout.
- [ ] **Tests:** checkout each type; reject insufficient balance (balance-only path); top-up-and-buy path; order idempotency; SSO new-user checkout.
**DoD:** checkout deducts balance correctly & issues grants; top-up-and-buy completes in one session; new customer account created inline.
**Depends:** Phase 2 (3 for end-to-end test).

## Phase 5 — Provisioning Layer + Licensing API
**Goal:** general provisioning layer running; `license_key` provisioner fully operational; OSS products can activate & validate.

### 5a — Provisioner layer (general)
- [ ] `LicenseKeyProvisioner` registered in `provisioning/registry.py`: `provision()` → creates `License` + `Grant(license_key)`.
- [ ] Lifecycle hooks wired: `suspend()`, `resume()`, `revoke()`, `renew()` cascade from Subscription state changes.
- [ ] **Tests:** provision → suspend → resume → revoke transitions; Grant status mirrors Subscription state.

### 5b — Activation API (Django Ninja `/v1`)
- [ ] Endpoints: `activate`, `validate`, `deactivate` per [07-api.md](07-api.md).
- [ ] Token signing + TTL (from `Setting`) + grace period; seat-limit enforcement; return Entitlements in response.
- [ ] `license_key` + product `secret` auth; rate limit (per-key + per-IP); log every attempt.
- [ ] **Superadmin panic controls** (journey §C-4): `Setting` key for global grace extension + maintenance mode flag that pauses validation failures (never bricks customers during API outage).
- [ ] **Self-serve device deactivation** (journey step 9): `deactivate` endpoint callable from Customer Dashboard; seat freed immediately.
- [ ] **Tests:** seat full, expired, revoked, suspended, idempotent activate, token refresh, grace period, maintenance mode bypass, rate limit.
**DoD:** activate→validate→deactivate cycle works; provisioner hooks cascade correctly; panic controls operational.
**Depends:** Phase 4.

## Phase 6 — Subscriptions & Background Jobs
**Goal:** recurring runs automatically.
- [ ] Celery/Django-Q + Redis.
- [ ] Renewal job (H-3): sufficient balance → auto-deduct + extend; short → grace → suspend (cascade to grants).
- [ ] Reactivation job on top-up; expired-token cleanup.
- [ ] **Tests:** renewal success/fail, grace→suspend→reactivate transitions, idempotent jobs.
**DoD:** subscriptions extend/suspend automatically based on balance.
**Depends:** Phases 2, 4, 5.

## Phase 7 — Notifications
**Goal:** the communication glue.
- [ ] WA abstraction (`notifications/whatsapp.py`) + email + templates.
- [ ] Hook events ([08-integrations.md](08-integrations.md) §8.4) via async jobs, subscribing to domain events.
**DoD:** events trigger notifications (mock/sandbox) without blocking the request.
**Depends:** Phases 3, 6.

## Phase 8 — Customer Dashboard (HTMX)
**Goal:** customer self-service — every state has an obvious next action; no support tickets for routine tasks.
- [ ] Balance widget + top-up shortcut + ledger history (paginated).
- [ ] My Products: Grant list per type; license key display + **1-click copy** + activation guide link.
- [ ] **Devices / Installations**: list seats, deactivate per device (calls activation API `deactivate`) — self-serve swap.
- [ ] Subscriptions: status + `current_period_end` + **auto-renew toggle** + renewal forecast ("next charge H-3 banner").
- [ ] **Renewal CTA**: when balance insufficient at H-3, banner shows balance shortfall + **top-up button** deeplinked to exact amount.
- [ ] Invoice/receipt PDF download; tax info field if business.
- [ ] Refund request form → creates admin task; shows "pending approval" state.
- [ ] Support shortcut (WA link / ticket form) with order context pre-filled.
**DoD:** customer can manage everything without contacting Admin; device swap, renewal, refund request all self-serve.
**Depends:** Phases 3, 4, 5, 6.

## Phase 9 — Public Storefront
**Goal:** people can buy.
- [ ] Catalog, product page, checkout UI, top-up UI, Contact (WA) button, top-up-and-buy.
**DoD:** the public register→top-up→buy flow is smooth.
**Depends:** Phases 4, 8.

## Phase 10 — Superadmin & Admin Tooling
**Goal:** owner runs full daily operations from the Operator Console (`/console/`) and Superadmin (`/admin/`).

### 10a — Superadmin first-run setup (journey §C-1)
- [ ] First-run checklist page (shown until all steps done): Duitku sandbox credentials → WA gateway → global settings (token TTL, grace days, min top-up, bonus rules) → tax/invoice identity → create StorePage → first product → invite Admins.
- [ ] All values backed by `Setting` model; editable from `/admin/` thereafter.

### 10b — Daily cockpit (Operator Console `/console/`)
- [ ] KPI cards: balance liability (SUM wallet balances), revenue recognized, active licenses, failed renewals, pending top-ups, new orders, open leads.
- [ ] **Unified work queue** (journey §B-2): incoming Leads + support tickets + **failed renewals** + failed-provisioning + stuck webhooks — all in one paginated queue with action buttons.

### 10c — Customer 360 (Admin support surface)
- [ ] One screen per customer: orders, balance ledger, licenses, devices, subscriptions, tickets, AuditLog timeline.
- [ ] Actions (all audited): resend key, resend invoice, extend subscription, transfer license, reset seat/device, manual top-up/adjustment (reason required).

### 10d — Money oversight
- [ ] Reconciliation view: Duitku settlement ↔ internal ledger delta.
- [ ] Refund approval queue → approve → `credit()` → notification.
- [ ] Reports/export (CSV): orders, top-ups, ledger, active subscriptions.

### 10e — Governance
- [ ] RBAC: create/edit Admin and Operator roles; assign per-surface capabilities.
- [ ] Audit log view (immutable, filterable by actor/action/target).
- [ ] Abuse controls: revoke license + flag account; **panic controls** (global grace extend, maintenance mode).

**DoD:** the owner can run full daily operations; first-run setup guides Superadmin to a working state; unified queue surfaces all actionable items.
**Depends:** Phases 1–9.

## Phase 11 — Polish & Multi-ready
- [ ] Promo/top-up bonus, coupons, broadcast. Additional provisioner types (credentials/account/api_key).
- [ ] Activate the `seller` concept (marketplace prep).
**DoD:** advanced features + schema ready for multi-seller.

---

### Minimum MVP path (demo-able end-to-end)
**Phase 0 → 1 → 2 → 3 → 4 → 5 → 6** = complete business core (top-up, buy, activate, recurring). Phases 7–10 add UX & operations.

---

## Post-launch expansion — Lynk.id parity

> Derived from [reviews/lynk-spec-adaptation.md](reviews/lynk-spec-adaptation.md). Honors the reconciliation principles: **no seller payout / no owner Free-PRO tiering in single-merchant** (deferred to multi-seller), **physical products skipped** (off digital/license positioning), and **extend Block/Provisioning, don't rebuild**. Phase 11.5 closes outstanding review items first.

## Phase 11.5 — Cleanup & Pre-production hardening
**Goal:** green CI + close remaining P0/P1 before feature expansion.
- [ ] Fix 12 stale tests (Operator-Group fixtures + checkout copy assertions) → CI green.
- [ ] Remove emoji `✓` in checkout; fix seller-home "This week" total (sum in view).
- [ ] **B-3:** document closed-loop balance (non-cash store credit) in ToS + ADR.
- [ ] **B-1 (external):** reconciliation report (Duitku settlement ↔ ledger).
- [ ] Verify purchase email includes the file/link (BUG-2); decide direct-pay vs wallet-first at checkout.
- [ ] Ops: Redis rate-limit in prod; money/concurrency tests on PostgreSQL; ledger backups; stable `PROVISIONING_SECRET_KEY`.
- [ ] Run the **live golden-path E2E** (Duitku sandbox) and capture each step.
**DoD:** CI green; P0 closed; one cycle proven live.

## Phase 12 — Rich Digital Products & Checkout depth
**Goal:** product/checkout depth matching Lynk's digital-product form (catalog/order layer only — never touches money core).
- [ ] Product/Plan fields ([adaptation §C](reviews/lynk-spec-adaptation.md)): rich-text description, image gallery + preview video, `sale_price`, **pay-what-you-want** (`pwyw` + `min_price`), `stock_quantity` (nullable=unlimited, atomic decrement), `max_qty_per_checkout`, `purchase_button_label`.
- [ ] **Custom questions** (`ProductQuestion`) → captured into `Order.custom_fields` (JSON); Name/Phone toggles enable WA follow-up.
- [ ] **Add-ons / order bumps** at checkout; **reviews** (`ProductReview`, rating + curated) + sold-count badge.
- [ ] Per-product: opt-in WA notification toggle, `custom_email_message`.
**DoD:** seller configures a rich product; buyer sees gallery/PWYW/sale price/reviews; checkout captures custom fields + add-ons; stock decrements atomically.
**Depends:** Phase 11.5.

## Phase 13 — Appearance/Theme editor, Live preview, File hosting & Delivery
**Goal:** storefront polish + reliable file delivery.
- [ ] **Theme editor** using `StorePage.theme`: banner, profile image, about, color picker, layout variants (Classic/Modern/Clean).
- [ ] **Block builder**: drag-drop reorder, per-block image/title/layout (Default/Grid/Large/Compact), `release_time` scheduling, enable/disable.
- [ ] **Live mobile preview** (iframe of draft state).
- [ ] **File upload + secure hosting** (S3-compatible, signed/expiring URLs); keep external-link option; **auto email delivery** + resend access.
- [ ] Mobile-first pass on storefront/checkout.
**DoD:** seller themes the page + reorders blocks with live preview; buyer receives the file via secure gated link + email.
**Depends:** Phase 12.

## Phase 14 — Course/E-course + new product types (via provisioning)
**Goal:** broaden product types through the `Deliverable`/`Provisioner` pattern.
- [ ] **Course**: `Deliverable.type=course` + `CourseProvisioner`; course/module/lesson models (video + PDF), player + progress.
- [ ] **Membership/community**: reuse `Subscription` + a `community` access grant.
- [ ] (Optional) **Event/ticketing**: `ticket` deliverable + QR + check-in scan. Blog/Media-kit as content `Block` types.
- [ ] **DIFFER:** physical products skipped (shipping/logistics off-positioning).
**DoD:** a course product sells and the buyer accesses the player with progress tracking.
**Depends:** Phase 13.

## Phase 15 — Analytics (funnel — differentiator) + Growth tools
**Goal:** real analytics + marketing automation.
- [ ] Per-block/link **views & clicks**, date-range, top products, sales distribution, social clicks.
- [ ] **Funnel analytics** (view → click → checkout → paid + conversion) — Lynk lacks this; our differentiator.
- [ ] **Email marketing** (broadcast + auto-responder); **automate-workflow** (trigger→action built on `core.events`); WA blast depth; custom post-purchase message.
- [ ] In-app **notification bell**; Tutorials/knowledge-base.
**DoD:** seller sees the conversion funnel and can run an email/automation campaign.
**Depends:** Phase 13.

## Phase 16 — Multi-seller activation (Stage 3)
**Goal:** open the platform; this is where Lynk's payout/tiering/affiliate finally apply.
- [ ] Finish per-seller isolation + public routing (`/s/<slug>`, StorePage per seller).
- [ ] **Seller earnings ledger + payout/withdrawal** (KYC/verify gate) — the seller-side wallet.
- [ ] **Affiliate program** (two-sided: be an affiliate / open one for your product).
- [ ] **Seller plans** (Free/PRO) + platform transaction fee (`Setting`).
- [ ] Custom domain + pixels/GA per seller.
**DoD:** a second seller can onboard (KYC), sell, and withdraw earnings.
**Depends:** Phases 12–15.
