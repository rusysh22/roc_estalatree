# Deep Evaluation — Estalatree (post Phase 11)

**Date:** 2026-06-19 · **Reviewer:** assistant (review-only; no code changed).
**Why this exists:** the earlier [ui-and-menu-enhancement-spec.md](ui-and-menu-enhancement-spec.md) was scoped to the 6 customer menus + rupiah. It was **not** the full picture. This document is the superset: header/app-shell, end-to-end business flow (owner lens), PRD blueprint traceability, and consolidated best-practice recommendations.

Severity: **P0** = correctness/trust/compliance (do before real customers) · **P1** = completeness · **P2** = polish/future.

---

## 1. Header / Navigation / App-shell

| # | Finding | Sev |
|---|---------|-----|
| H-1 | **No persistent balance in the header.** For a prepaid-wallet product (Sumopod/Lynk pattern) the saldo + "Top up" should be visible on every page. Today the customer must open Wallet to see balance. | P1 |
| H-2 | **Devices page is orphaned** — `/dashboard/devices/` exists but is not in the nav (reachable only via Products). Add it (or nest clearly). | P1 |
| H-3 | No active-page indicator; no in-app notification center (bell); **no footer** (Terms / Privacy / Contact) — legal pages are expected on a commerce site. | P2 |
| H-4 | **HTMX loaded from unpkg CDN** (`dashboard/base.html`). Vendor it locally (reliability, CSP, offline, supply-chain). | P1 |
| H-5 | Each surface (dashboard / storefront / console / seller) has its own nav. Acceptable, but extract a shared shell partial for consistency. | P2 |
| H-6 | **No surface switcher for multi-role accounts.** ADR-017 allows one account = operator + customer + seller, but moving between `/console`, `/dashboard`, `/seller` is manual URL editing. Add a role-aware switcher. | P1 |

---

## 2. End-to-end business flow (owner lens)

Tracing money-in → provisioning → usage → renewal → support → refund, and the books behind it.

| # | Seam | Finding | Sev |
|---|------|---------|-----|
| B-1 | **Books integrity** | No reconciliation between Duitku settlements and the ledger; refund credits the wallet but does **not** set `Order.REFUNDED`, so the revenue KPI is gross of refunds. The owner cannot trust/close the books — the whole point of the liability-vs-revenue split. | **P0** |
| B-2 | **Secrets at rest** | `credentials`/`api_key` grants store secrets plaintext in `Grant.payload` (+ `deliverable.config`); the encrypted `Secret` model is unused. | **P0** |
| B-3 | **Closed-loop legal** | Balance is wallet-only refundable (good), but "closed-loop store credit, non-cash, non-transferable" is not stated in ToS or an ADR → e-money regulatory posture undocumented. | **P0** |
| B-4 | **Coupon redemption** | `used_count` increment is read-then-write (not `F()`/conditional) → `usage_limit` can be exceeded under concurrency; verify redemption is also recorded on the top-up-and-buy path. | P1 |
| B-5 | **Activation hand-off** | After purchase there is no copy-key + activation guide on Products — the highest-friction moment in the journey is unfinished. | P1 |
| B-6 | **Entitlements** | Defined on plans and returned in the activation response, but there is **no management UI** (attach entitlements to a plan in seller/console) and no enforcement demonstration → the "feature gating" pillar is half-built. | P1 |
| B-7 | **Tax / invoice** | No PDF, no PPN line, no merchant identity on invoices → cannot serve business buyers or meet compliance. | P1 |
| B-8 | **Support loop** | WA-only; no ticket trail / history / SLA. | P2 |
| B-9 | **Email verification** | `ACCOUNT_EMAIL_VERIFICATION="optional"` → unverified emails can transact; decide required + gate purchase/top-up. | P1 |
| B-10 | **Multi-seller** | Seller dashboard is scoped, but StorePage editing falls back to the first page (cross-store mutation) and the public storefront is not per-seller. Either fence honestly to single-merchant or finish per-seller isolation + routing. | P1 |
| B-11 | **Ops/reliability** | Confirm rate-limit cache is Redis in prod (per-process LocMem won't span workers); run money/concurrency tests on PostgreSQL (SQLite `select_for_update` is a no-op); back up the ledger; `account` deliverable + external-provisioner async-fulfillment remain future. | P1 |

**What is genuinely solid (end-to-end):** top-up → ledger (idempotent + webhook safety net), checkout + top-up-and-buy (idempotent, provision-in-atomic), license activate/validate/deactivate + cascade, subscription renew/grace/suspend/reactivate, notifications (dedup + shortfall-only), panic controls (now wired), refund→wallet + audit. The money spine is trustworthy; the gaps are at the edges (books closing, secrets, compliance, feature-completion).

---

## 3. PRD blueprint traceability

| PRD area (doc) | Implemented | Gap |
|----------------|-------------|-----|
| Wallet/Ledger (03 §3.1) | Yes | — |
| Token/Activation (03 §3.2, 07) | Yes | validate-requires-active-install (Phase 5 M1) confirm; fingerprint grace re-bind (open) |
| Products & pricing (04, 17) | Yes | unlisted accessibility; add-ons/bundles (future) |
| Flows (05) | Yes | refund→Order.REFUNDED (B-1) |
| Data model (06) | Yes | — |
| Integrations/Notifications (08) | Yes | broadcast async (M3); WA gateway final choice |
| Features per module (09) | Mostly | reconciliation/abuse views; support tickets |
| Non-functional (10) | Mostly | Redis rate-limit in prod; ledger backups |
| Provisioning & Entitlements (15) | Partial | secrets plaintext (B-2); entitlement mgmt UI (B-6); `account` provisioner missing |
| Auth & SSO (16) | Partial | Google button surfaced? verify; 2FA for admin surfaces; email-verify required |
| Product packaging (17) | Core only | add-ons/bundles future |
| Product evolution (18) | Stage 0–1 + parts of 2/3 | reconciliation (Stage 1); themes/domains/pixels/affiliate (Stage 2/3) |
| Extensibility (19) | Yes | events/registry/Setting in use |
| UI/IA (20) | Mostly | header balance/switcher (H-1/H-6); footer |
| User journeys (21) | Mostly | activation hand-off (B-5); support ticket (B-8) |
| Feature catalog (22) | Stage-0 baseline | Stage-2/3 items intentionally pending |
| Configuration (23) | Yes | secret helper to end plaintext pattern (B-2) |

**Verdict:** the blueprint is broadly accommodated through Stage-0/1. The unbuilt items are either flagged gaps (P0/P1 above) or explicitly future (Stage-2/3 in 18/22). No PRD pillar is missing by accident.

---

## 4. Consolidated best-practice recommendations (prioritized)

**P0 — before real customers**
1. **Close the books:** reconciliation view (Duitku settlement ↔ ledger) + set `Order.REFUNDED` on refund + net refunds out of revenue KPI. (B-1)
2. **Encrypt secrets:** move `credentials`/`api_key` into the `Secret` model (encrypted, reveal-once); add a shared `get_secret()` helper for gateway keys. (B-2)
3. **Document closed-loop balance** in ToS + an ADR (non-cash store credit). (B-3)

**P1 — completeness**
4. Header: persistent balance + Top-up; Devices in nav; vendor HTMX; surface switcher for multi-role. (H-1/2/4/6)
5. Rupiah filter + TYPE-label bug — see [ui-and-menu-enhancement-spec.md](ui-and-menu-enhancement-spec.md) §0/§0b.
6. Activation hand-off: copy-key + guide on Products. (B-5)
7. Coupon atomic redemption (`F()` + conditional). (B-4)
8. Invoices: PDF + invoice number + merchant identity + PPN decision. (B-7)
9. Entitlement management UI + enforcement story. (B-6)
10. Email verification decision + gate. (B-9)
11. Multi-seller: finish isolation/routing or fence to single-merchant. (B-10)
12. Ops: Redis rate-limit in prod; money tests on Postgres; ledger backups. (B-11)

**P2 — polish/future**
13. Support tickets; notification preferences; in-app notification bell; footer/legal pages; themes/custom-domain/pixels/affiliate (Stage 2/3).

---

## 5. Bottom line
The engine is production-track and trustworthy; review discipline has been excellent. What stands between "feature-complete per phase" and "a business you can run on real money" is a small, bounded set: **close the books (B-1), secure secrets (B-2), document the legal posture (B-3)** — then the P1 completeness items. None require architectural rework.
