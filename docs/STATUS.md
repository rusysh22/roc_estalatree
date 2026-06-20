# STATUS — Estalatree Progress Board

> **Update this file whenever a task is completed.** It is the source of truth for cross-agent handoff. Format: check `[x]` + date + short note.

**Active phase:** **Pre-production hardening** — all build phases (0–11, incl. 9.5) implemented; all P0/P1 review findings closed except B-3 (ToS doc) and B-11 (ops).
**Last updated:** 2026-06-20 — P0/P1 remediation complete. See [reviews/](reviews/).

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
- [x] **Phase 9.5** — Unified UI shell + styled auth + `seed_demo` *(2026-06-19)*
- [x] **Phase 10** — Operator Console (+ Phase 8/9/10 review fixes) *(2026-06-19)*
- [x] **Phase 11** — Polish & Multi-ready: seller dashboard, coupons, top-up bonus, extra provisioners *(2026-06-19)*

**Minimum MVP:** Phases 0–6.

> Note: the build plan ([12](12-build-plan.md)) predates the generalized provisioning model ([15](15-provisioning-and-entitlements.md)) and persona feature additions (§ Backlog). Reconcile during Phase 1 — Phase 5 becomes "Licensing as the `license_key` provisioner" within a general provisioning layer.

---

## Work Log (per task)
- 2026-06-19 — Full-cycle review: verified all per-phase HIGH fixes closed (checkout_token, Setting-key sync, refund lock+deterministic ref + superuser-only, export `type`, audit case). New findings logged in [reviews/final-review.md](reviews/final-review.md), [reviews/deep-evaluation.md](reviews/deep-evaluation.md), [reviews/ui-and-menu-enhancement-spec.md](reviews/ui-and-menu-enhancement-spec.md). Consolidated outstanding items above (P0/P1/P2).
- 2026-06-19 — Phase 11: seller dashboard (Lynk.id-style, scoped), `Coupon` model + checkout discount wiring, top-up bonus, credentials/api_key/download/access_link/manual provisioners registered. (Open: secrets plaintext, coupon race, multi-seller isolation, broadcast sync.)
- 2026-06-19 — Phase 10: Operator Console (cockpit + work queue, Customer 360, refund queue, manual credit, extend, CSV export, audit view, settings + panic) + Phase 8/9/10 review fixes applied.
- 2026-06-19 — Phase 9.5: unified `templates/base.html` shell, styled auth, `seed_demo` command.
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

## Outstanding (from full-cycle review — see [reviews/](reviews/))

Per-phase HIGH findings are all verified **closed** (see review docs). Remaining, by severity:

**P0 — before real customers**
- [x] **Encrypt secrets** — credentials/api_key Fernet-encrypted via `provisioning/crypto.py` + `Secret`; reveal-once (B-5). *(2026-06-20)*
- [~] **Close the books** — DONE: refund sets `Order.REFUNDED` + revenue KPI excludes refunds. PENDING: external reconciliation (Duitku settlement ↔ ledger) report. (deep-eval B-1)
- [ ] **Closed-loop balance** documented in ToS (non-cash store credit, no withdrawal). (deep-eval B-3) — **policy/legal doc, not code**

**P1 — completeness**
- [x] Rupiah filter system-wide + TYPE-label bug. *(2026-06-20)*
- [x] Coupon atomic redemption with strict `used_count__lt` conditional. *(2026-06-20)*
- [x] Header: balance chip + Top-up; Devices in nav; HTMX off unpkg. *(2026-06-20)*
- [x] Broadcast async (`deliver_whatsapp.delay`). · [x] Store isolation. *(2026-06-20)*
- [x] Activation hand-off: setup instructions panel on Products page. *(2026-06-20)*
- [x] Invoices: sequential invoice number + printable HTML invoice detail page. (B-7) *(2026-06-20)*
- [x] Entitlement management UI (seller plan_edit) + Grant.has_entitlement check. (B-6) *(2026-06-20)*
- [x] Email verification gate — warning at checkout + topup. (B-9) *(2026-06-20)*
- [x] Console gated on `Operator` group OR superuser (ADR-017). *(2026-06-20)*
- [x] **Crypto key**: `PROVISIONING_SECRET_KEY` env var (separate from `SECRET_KEY`); documented in `.env.example`. *(2026-06-20)*
- [x] Notification preferences (WA/email toggle on profile page). *(2026-06-20)*
- [x] Footer: Terms/Privacy/Contact on storefront + dashboard. *(2026-06-20)*
- [x] Gated download: `/dashboard/grants/<pk>/download/` validates ownership before redirect. *(2026-06-20)*
- [x] Seller analytics: 7-day revenue chart + per-product stats on home + products pages. *(2026-06-20)*
- [ ] Ops: Redis rate-limit in prod; money tests on PostgreSQL; ledger backups. (B-11) — **infra/ops, not app code**

**P2 — polish/future**
- [ ] Support tickets system.
- [ ] In-app notification bell (requires Notification model + HTMX polling).
- [ ] Multi-role surface switcher UI improvement (H-6).
- [ ] Stage-2/3: themes, custom domain, pixel tracking, affiliate.

**Pre-production proof**
- [ ] Run the **live golden-path E2E** (Duitku sandbox) end-to-end and capture each step.

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
