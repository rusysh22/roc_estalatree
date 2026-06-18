# STATUS — Estalatree Progress Board

> **Update this file whenever a task is completed.** It is the source of truth for cross-agent handoff. Format: check `[x]` + date + short note.

**Active phase:** **Phase 0** — Setup & Stability Layer (in progress).
**Last updated:** 2026-06-18 — ADR closed-loop locked (ADR-019, compliance quick-ref); build plan reconciled with journey requirements + provisioning model; Phase 0 scaffold started.

---

## Phase Progress (summary — details in [12-build-plan.md](12-build-plan.md))

- [x] **Phase 0** — Setup & Project Standards *(2026-06-18)*
- [ ] **Phase 1** — Domain Models (Spine)
- [ ] **Phase 2** — Wallet & Ledger (MONEY)
- [ ] **Phase 3** — Top-up (Duitku)
- [ ] **Phase 4** — Catalog & Checkout
- [ ] **Phase 5** — Licensing & Activation API
- [ ] **Phase 6** — Subscriptions & Background Jobs
- [ ] **Phase 7** — Notifications
- [ ] **Phase 8** — Customer Dashboard (HTMX)
- [ ] **Phase 9** — Public Storefront
- [ ] **Phase 10** — Superadmin & Admin Tooling
- [ ] **Phase 11** — Polish & Multi-ready

**Minimum MVP:** Phases 0–6.

> Note: the build plan ([12](12-build-plan.md)) predates the generalized provisioning model ([15](15-provisioning-and-entitlements.md)) and persona feature additions (§ Backlog). Reconcile during Phase 1 — Phase 5 becomes "Licensing as the `license_key` provisioner" within a general provisioning layer.

---

## Work Log (per task)
- 2026-06-18 — Docs: ADR closed-loop locked (ADR-019 Python/Django pin, compliance quick-ref table). Build plan reconciled with journey requirements (top-up-and-buy Phase 4, inline SSO Phase 4, webhook safety net Phase 3, unified work queue Phase 10, Superadmin first-run Phase 10, self-serve device mgmt Phase 8, panic controls Phase 5b/10e, Customer 360 Phase 10c, provisioning layer explicit Phase 1/5).
- 2026-06-18 — Phase 0: Full scaffold committed. `manage.py check` → 0 issues. uv lockfile committed. Includes: pyproject.toml (Django 5.2 + Ninja + allauth + Celery + Sentry + structlog), settings base/dev/prod, docker-compose.yml (pg+redis), .env.example, all 12 app skeletons (accounts wallet catalog billing provisioning licensing storefront console dashboard crm notifications core), core base models (TimestampedModel, SellerScopedModel, AuditLog, Setting), event bus (core/events.py), audit helper (core/audit.py), provisioner registry (provisioning/registry.py), CI (GitHub Actions: lint+test+makemigrations+pip-audit), pre-commit (black+ruff+isort+detect-secrets), golden-path smoke test stub (4 xfail stubs + 4 structural assertions).

---

## Final Decisions (do not change without user instruction)
See [DECISIONS.md](DECISIONS.md). Stack, balance model, Duitku-for-topup, online validation, single-merchant multi-ready, generalized provisioning, entitlements, allauth/Google SSO, English standard, immutable ledger.

---

## Resolved
- ✅ License key format: plain `XXXX-XXXX-XXXX`, no prefix.
- ✅ Language standard: English.
- ✅ Auth: django-allauth + Google SSO.
- ✅ "Sell more than licenses": generalized Deliverable/Provisioner/Grant model.
- ✅ Admin UI: hybrid (custom HTMX cockpit + Django Admin).
- ✅ Storefront: link-in-bio shareable page (StorePage + Blocks) — see [20-ui-information-architecture.md](20-ui-information-architecture.md).
- ✅ Checkout UX: top-up-and-buy default + inline Google SSO — see [21-user-journeys.md](21-user-journeys.md).
- ✅ Refund: wallet credit only. First-purchase top-up: suggested packages + pay-exact. Anonymous browsing: allowed.
- ✅ Access surfaces split: `/admin/` (Superadmin) · `/console/` (Operator) · `/dashboard/` (Customer) · storefront; one account, multiple roles.
- ✅ Lynk.id PRO features = baseline/all-access for owner, no tiering — see [22-feature-catalog.md](22-feature-catalog.md).
- ✅ Stability layer in Phase 0: uv lockfile, CI (GitHub Actions), secret scanning, factory_boy, Sentry/logging, golden-path smoke test.
- ✅ UI icons: Heroicons SVG (inline/sprite), no emoji anywhere.

## Open Questions (need user decision before/at the related phase)
- [ ] **WA gateway** — Fonnte / Wablas / official WhatsApp Business API? (Phase 7)
- [ ] **Installation fingerprint strategy** — what signals; tolerance to hardware change. (Phase 5)
- [ ] **PPN/tax** on invoices — needed or not. (Phase 4/8)
- [ ] **Default grace period** length (days). (Phase 5/6)
- [ ] **Duitku** sandbox credentials + min top-up + bonus rules. (Phase 3)
- [ ] **Default auto-renew** on/off for new subscriptions. (Phase 6)
- [ ] **Secret encryption** approach for `credentials`/`api_key` grants (e.g. Fernet/KMS). (Phase 5/Stage 2)
- [ ] **External account provisioning** targets — which systems do `account`/`api_key` provisioners call? (Stage 2)

## Pending Housekeeping
- [x] Convert all docs to English (done 2026-06-18).
- [x] Fold journey requirements + provisioning model into build plan (done 2026-06-18): top-up-and-buy (Phase 4), inline SSO (Phase 4), webhook safety net (Phase 3), Admin unified work queue (Phase 10), Superadmin first-run checklist (Phase 10), self-serve device mgmt (Phase 8), panic controls (Phase 5b/10e), Customer 360 (Phase 10c). See [12-build-plan.md](12-build-plan.md).
- [ ] Fold remaining persona feature additions into [09-features.md](09-features.md) (reconciliation view, forecast/alerts, broadcast, vouchers — Phase 10/11 scope).
- [ ] (Optional) Renumber docs into logical reading order.
