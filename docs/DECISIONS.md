# DECISIONS — Architecture Decision Log (ADR-lite)

> Records each decision **and its rationale** so future agents/sessions don't undo it without context. Newest on top. Keep entries short.
>
> **Closed-loop status:** All ADRs below are **Accepted / Final**. Do not change without explicit user instruction. If a new decision is needed, add a new ADR (next: ADR-020) and note it in [STATUS.md](STATUS.md).

---

## Compliance Quick-Reference

| Area | Rule in code |
|------|-------------|
| **Money** | `PositiveBigIntegerField` whole IDR; all mutations via `wallet/services.py` only; `LedgerEntry` immutable (no update/delete). |
| **IDs** | Internal PK `BigAutoField`; external URLs use prefixed `public_id` (`ord_`, `top_`, …); license key = plain `XXXX-XXXX-XXXX` (no prefix). |
| **Recurring** | Auto-deduct from balance; never auto-debit via gateway; grace → suspend cascade via Provisioner hooks. |
| **Provisioning** | Every new thing to sell → new `Provisioner` in registry; never a checkout special case. |
| **Feature gating** | Via `Entitlement` keys on Grants; never branch on plan name in code. |
| **Auth** | django-allauth; Google SSO inline at checkout (no signup wall); 2FA for admin surfaces. |
| **Admin** | `LedgerEntry`/`AuditLog` blocked from update/delete in Django Admin; Superadmin-only `/admin/`. |
| **API** | Django Ninja `/v1`; consistent `{status, message, code}` error envelope; online validation (not offline JWT). |
| **Events** | Cross-feature reactions via domain events (`core.events`), not direct cross-app imports. |
| **Secrets** | Never in repo; `.env.example` committed without values; secret grants encrypted at rest. |
| **Language** | English in all code, docs, and base UI strings. |
| **Icons** | Heroicons SVG inline/sprite; no emoji in UI. |

---

### ADR-019 — Python 3.12 + Django 5.2 LTS pinned
**Status:** Accepted · 2026-06-18
**Decision:** Pin Python 3.12 and Django 5.2 LTS (current LTS as of June 2026). uv lockfile pins all transitive deps. Upgrade only on explicit user decision.
**Why:** 3.12 is stable + LTS; Django 5.2 is the supported LTS with security backports until April 2028. Python 3.13/3.14 not yet validated by the full dep tree (allauth, psycopg, celery).

### ADR-018 — No owner-side tiering; Lynk.id PRO features are baseline/all-access
**Status:** Accepted · 2026-06-18
**Decision:** There is no "Upgrade to PRO" for the owner. All Lynk.id PRO capabilities (custom domain, themes, multi-page, white-label, analytics/pixels, WA broadcast, course/forms, affiliates) are baseline with no caps, scheduled across stages by effort. Tiering + marketplace fees (transaction/withdrawal) re-appear only as *Seller* plans in the multi-seller stage.
**Why:** Single-merchant owns the platform; caps/tiers were Lynk's monetization levers, irrelevant to the owner. ([22-feature-catalog.md](22-feature-catalog.md))

### ADR-017 — Separate access surfaces; Django Admin is Superadmin-only
**Status:** Accepted · 2026-06-18 (refines ADR-013)
**Decision:** Four surfaces on separate URLs — Django Admin (`/admin/`, **Superadmin only**), Operator Console (`/console/`, custom HTMX for Admin/Operator + Superadmin), Customer Dashboard (`/dashboard/`), Storefront. One `User` may hold multiple roles (operator/seller who is also a customer, esp. multi-seller); surfaces gated by capability.
**Why:** Operators shouldn't get raw DB power (least privilege); cleaner separation; supports multi-role identity for the multi-seller future. ([20-ui-information-architecture.md](20-ui-information-architecture.md))

### ADR-016 — Inline 1-click account (Google SSO) at checkout
**Status:** Accepted · 2026-06-18
**Decision:** No separate signup wall; account is created inline via Google SSO at the point of purchase.
**Why:** Minimize first-purchase friction. ([21-user-journeys.md](21-user-journeys.md))

### ADR-015 — Top-up-and-buy is the default first-purchase path
**Status:** Accepted · 2026-06-18
**Decision:** When balance is insufficient at checkout, a single Duitku transaction funds (exact/suggested) **and** completes the purchase. Returning customers with balance buy instantly.
**Why:** The balance model must not feel like an extra step for one-off buyers; the upfront funding is paid once, repeats/recurring become frictionless. ([21-user-journeys.md](21-user-journeys.md))

### ADR-014 — Link-in-bio storefront (Lynk.id-style)
**Status:** Accepted · 2026-06-18
**Decision:** Public storefront is a shareable link-in-bio page (`StorePage` composed of `Block`s) with an Appearance/theme, plus product pages + checkout. Start with `product` + `link` blocks.
**Why:** Matches the "like lynk.id" goal; flexible and shareable. ([20-ui-information-architecture.md](20-ui-information-architecture.md))

### ADR-013 — Hybrid admin UI (custom cockpit + Django Admin)
**Status:** Accepted · 2026-06-18
**Decision:** Daily owner cockpit is custom HTMX (designed, KPI-driven); Django Admin handles deep CRUD/back-office.
**Why:** Get a polished Lynk.id-like cockpit without rebuilding all CRUD; fast + clean. ([20-ui-information-architecture.md](20-ui-information-architecture.md))

### ADR-012 — Domain events for extensibility
**Status:** Accepted · 2026-06-18
**Decision:** Core operations emit domain events; features subscribe via async jobs.
**Why:** Lets us add notifications/analytics/provisioners without editing core flows ([19-extensibility.md](19-extensibility.md)).

### ADR-011 — Authentication via django-allauth (email/password + Google SSO)
**Status:** Accepted · 2026-06-18
**Decision:** Use django-allauth; Google OAuth2 with PKCE; 2FA for admins. Enterprise SAML/SCIM out of scope.
**Why:** Standard, batteries-included for consumer SaaS; minimal effort, extensible to more providers. ([16-auth-and-sso.md](16-auth-and-sso.md))

### ADR-010 — Entitlements as first-class objects (feature gating)
**Status:** Accepted · 2026-06-18
**Decision:** Features gated by Entitlement keys attached to Plans/Grants, not by plan name.
**Why:** Keygen/feature-flag best practice; ship features without migrations or plan-by-plan branching.

### ADR-009 — Generalized provisioning (Deliverable + Provisioner + Grant)
**Status:** Accepted · 2026-06-18
**Decision:** What's sold is an Entitlement fulfilled by a pluggable Provisioner producing a Grant. License key is one Grant type; others: credentials/password, account, download, api_key, manual.
**Why:** User needs to sell more than licenses (e.g. generated passwords). Plugin registry = add capabilities without core rewrite. ([15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md))

### ADR-008 — English as the system default language
**Status:** Accepted · 2026-06-18
**Decision:** English is the standard for code, docs, and base UI. Indonesian/other locales via Django i18n later.
**Why:** Consistency and broader maintainability. Guarded as a standing standard.

### ADR-007 — License key is a plain hash `XXXX-XXXX-XXXX` (no prefix)
**Status:** Accepted · 2026-06-18
**Decision:** No `ESTL-`/product prefix on license keys; plain three-group Base32 hash.
**Why:** User preference; cleaner to read/copy. (Prefixed `public_id` still used for Order/TopUp/etc.)

### ADR-006 — Money as whole-rupiah integers
**Status:** Accepted · 2026-06-18
**Decision:** `PositiveBigIntegerField` whole rupiah, not Decimal/float.
**Why:** IDR has no practical subunit; avoids float rounding; simplifies the ledger.

### ADR-005 — `seller` modeled but not activated
**Status:** Accepted · 2026-06-18
**Decision:** Single-merchant now; `seller` columns present (default one seller).
**Why:** Fast launch without marketplace complexity, no schema rewrite when opening multi-seller.

### ADR-004 — Online license validation (not offline JWT)
**Status:** Accepted · 2026-06-18
**Decision:** OSS products activate & heartbeat online; short token + grace period.
**Why:** Need real-time revocation when a subscription lapses; grace covers offline tolerance.

### ADR-003 — Duitku used only for top-up
**Status:** Accepted · 2026-06-18
**Decision:** Duitku funds the wallet; product checkout deducts internal balance.
**Why:** One reconciliation point; enables recurring via balance auto-deduct.

### ADR-002 — Recurring via balance auto-deduct (not auto-debit)
**Status:** Accepted · 2026-06-18
**Decision:** Renewals deduct from balance; if short → reminder → grace → suspend.
**Why:** Indonesian gateways lack reliable auto-debit; prepaid (Sumopod-style) fits the market and solves recurring.
**Consequence:** Depends on customer top-up discipline + effective reminders.

### ADR-001 — Stack: Django + Django Ninja + HTMX
**Status:** Accepted · 2026-06-18
**Decision:** Django monolith; Django Admin for admin panel; Django Ninja for activation API; HTMX+Tailwind for storefront/dashboard.
**Why:** "Dynamic & not complicated" — admin nearly free, typed modern API, one codebase/DB; avoids SPA/microservice overhead early.
