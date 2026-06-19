# STATUS — Estalatree Progress Board

> **Update this file whenever a task is completed.** It is the source of truth for cross-agent handoff. Format: check `[x]` + date + short note.

**Active phase:** **Pre-production hardening** — all build phases (0–11, incl. 9.5) implemented; remediation of review findings in progress.
**Last updated:** 2026-06-19 — Phases 9.5 / 10 / 11 complete; full-cycle deep evaluation done. See [reviews/](reviews/) — esp. [final-review.md](reviews/final-review.md) and [deep-evaluation.md](reviews/deep-evaluation.md).

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
- [ ] **Close the books**: reconciliation (Duitku settlement ↔ ledger) + set `Order.REFUNDED` on refund + net refunds out of revenue KPI. ([deep-evaluation.md](reviews/deep-evaluation.md) B-1)
- [ ] **Encrypt secrets**: move `credentials`/`api_key` into the `Secret` model (reveal-once); shared `get_secret()` helper. ([final-review.md](reviews/final-review.md) H1, deep-eval B-2)
- [ ] **Closed-loop balance** documented in ToS + ADR (non-cash store credit). (deep-eval B-3)

**P1 — completeness**
- [ ] Rupiah filter system-wide + ledger TYPE-label bug (`get_type_display`). ([ui-and-menu-enhancement-spec.md](reviews/ui-and-menu-enhancement-spec.md) §0/§0b)
- [ ] Coupon atomic redemption (`F()` + conditional) incl. top-up-and-buy path. (final-review M1)
- [ ] Header: persistent balance + Top-up; Devices in nav; vendor HTMX; multi-role surface switcher. (deep-eval H-1/2/4/6)
- [ ] Activation hand-off: copy-key + guide on Products; reveal-once for credential grants. (deep-eval B-5, ui-spec §2.2)
- [ ] Invoices: PDF + invoice number + merchant identity + PPN decision. (deep-eval B-7)
- [ ] Entitlement management UI + enforcement. (deep-eval B-6)
- [ ] Email verification decision + gate; multi-seller finish-or-fence; broadcast async. (deep-eval B-9/B-10, final-review M3)
- [ ] Ops: Redis rate-limit in prod; money tests on PostgreSQL; ledger backups. (deep-eval B-11)
- [ ] Residual: console gated on `is_staff` → dedicated Group (ADR-017). (phase-10-review H2a)

**P2 — polish/future**
- [ ] Support tickets; notification preferences; in-app notification bell; footer/legal pages; Stage-2/3 (themes, custom domain, pixels, affiliate).

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
