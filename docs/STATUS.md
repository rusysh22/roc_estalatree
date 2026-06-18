# STATUS — Estalatree Progress Board

> **Update this file whenever a task is completed.** It is the source of truth for cross-agent handoff. Format: check `[x]` + date + short note.

**Active phase:** **Phase 10** — Superadmin & Admin Tooling — next.
**Last updated:** 2026-06-18 — Phase 9 complete: public storefront (store page with blocks, product detail, checkout, top-up-and-buy, contact Lead flow, order status), 17 tests green (153 total).

---

## Phase Progress (summary — details in [12-build-plan.md](12-build-plan.md))

- [x] **Phase 0** — Setup & Project Standards *(2026-06-18)*
- [x] **Phase 1** — Domain Models (Spine) *(2026-06-18)*
- [x] **Phase 2** — Wallet & Ledger (MONEY) *(2026-06-18)*
- [x] **Phase 3** — Top-up (Duitku) *(2026-06-18)*
- [x] **Phase 4** — Catalog & Checkout *(2026-06-18)*
- [x] **Phase 5** — Licensing & Activation API *(2026-06-18)*
- [x] **Phase 6** — Subscriptions & Background Jobs *(2026-06-18)*
- [x] **Phase 7** — Notifications *(2026-06-18)*
- [x] **Phase 8** — Customer Dashboard (HTMX) *(2026-06-18)*
- [x] **Phase 9** — Public Storefront *(2026-06-18)*
- [ ] **Phase 10** — Superadmin & Admin Tooling
- [ ] **Phase 11** — Polish & Multi-ready

**Minimum MVP:** Phases 0–6.

> Note: the build plan ([12](12-build-plan.md)) predates the generalized provisioning model ([15](15-provisioning-and-entitlements.md)) and persona feature additions (§ Backlog). Reconcile during Phase 1 — Phase 5 becomes "Licensing as the `license_key` provisioner" within a general provisioning layer.

---

## Work Log (per task)
- 2026-06-18 — Docs: ADR closed-loop locked (ADR-019 Python/Django pin, compliance quick-ref table). Build plan reconciled with journey requirements (top-up-and-buy Phase 4, inline SSO Phase 4, webhook safety net Phase 3, unified work queue Phase 10, Superadmin first-run Phase 10, self-serve device mgmt Phase 8, panic controls Phase 5b/10e, Customer 360 Phase 10c, provisioning layer explicit Phase 1/5).
- 2026-06-18 — Phase 3: billing/duitku.py (DuitkuClient, InvoiceResult, TransactionStatus, signature verification); billing/services.py (initiate_topup, process_webhook_payload with savepoint idempotency, recheck_topup_status safety-net); billing/views.py (duitku_webhook, csrf_exempt, 200/400/500 responses); billing/tasks.py (poll_pending_topups Celery safety-net); tests/test_topup.py (13 tests: initiate, success, bonus, duplicate, invalid-sig, non-success, view HTTP, recheck). All 38 tests pass.
- 2026-06-18 — Phase 2: wallet/services.py (credit + debit — atomic select_for_update, idempotent ref, InsufficientBalance guard); wallet/signals.py auto-creates Wallet on Customer.post_save (H3); tests/factories.py (User/Customer/Wallet); tests/test_wallet.py (21 tests: balance invariant, idempotency, overdraw, concurrency, immutability). docker-compose postgres remapped to port 5434 (5432 occupied by roc_support_desk).
- 2026-06-18 — Phase 1 review fixes: H1 custom User (email/password, no username, AbstractBaseUser+PermissionsMixin, AUTH_USER_MODEL=accounts.User); H2 LedgerEntry+AuditLog save/delete raise TypeError at model level; H4 events.emit() via transaction.on_commit; M3 assign_unique_public_id/assign_unique_license_key with retry loop; L1 removed redundant Index on LedgerEntry.ref + License.key (unique=True already indexes). All migrations reset and regenerated.
- 2026-06-18 — Phase 1: All domain models written + 9 initial migrations. SellerProfile, Customer, Wallet, LedgerEntry (immutable admin), Product, Plan, Order, TopUp, PaymentWebhook, Subscription, Deliverable, Entitlement (M2M Plans), Grant (has_entitlement/get_entitlements), Secret, License (XXXX-XXXX-XXXX Crockford key auto-gen, active_seat_count property), Installation (partial-unique constraint), Lead. All models in Django Admin (LedgerEntry/PaymentWebhook read-only). `manage.py check` 0 issues; `makemigrations --check` no changes.
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
