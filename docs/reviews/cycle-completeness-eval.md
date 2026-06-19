# Cycle Completeness Evaluation

**Date:** 2026-06-19 · **Reviewer:** assistant (review-only; no code changed)
**Trigger:** raw/unstyled allauth login at `localhost:5000/accounts/login/`.
**Verdict:** **Not 100% yet.** The business engine (Phase 0–10) is functionally complete and tested. The **presentation layer and auth integration are not done**, and several HIGH review items are still open. The screenshot is a symptom: auth runs on default allauth templates with no styling.

---

## Layered status

| Layer | Status |
|-------|--------|
| Domain models / money / ledger | Done, tested |
| Top-up (Duitku) + safety net | Done |
| Checkout + top-up-and-buy + provisioning | Done (Phase 9 H1 checkout_key fix pending) |
| Activation API + licensing cascade | Done (Phase 5 items: confirm applied) |
| Subscriptions + jobs | Done |
| Notifications (backend) | Done (emoji-in-message decision pending) |
| Auth (backend config) | Done — allauth + Google provider configured |
| **Auth UI** | **Missing** — default allauth templates, unstyled |
| **Unified UI shell / Tailwind / Heroicons** | **Missing** — project `templates/` empty; 3 disjoint app bases |
| **Google SSO surfaced in UI** | **Missing** — no provider button on login |
| Operator Console (Phase 10) | Built but **uncommitted**; H1/H2/H3 open |

---

## What the screenshot reveals
1. **No unified UI shell / styling.** `templates/` (project-level, on `TEMPLATES.DIRS`) is empty → allauth falls back to its raw default templates. `storefront`/`dashboard`/`console` each have their own `base.html`; auth has none.
2. **Google SSO not in the UI.** `allauth.socialaccount.providers.google` + `SOCIALACCOUNT_PROVIDERS` are configured, but the login page shows only email/password — no provider button (template not overridden and/or `SocialApp` credentials not set). ADR-016 (inline SSO at checkout) is not realized in the UI.
3. **No branding** — default "Menu / Sign In / Sign Up"; no link back to storefront/dashboard.
4. **`ACCOUNT_EMAIL_VERIFICATION = "optional"`** vs [../16-auth-and-sso.md](../16-auth-and-sso.md) (verification required before purchase/top-up) — decide.
5. **No seed user** (login attempt failed) — need demo/seed data to click through.

## Open correctness items blocking "complete"
- **Phase 10 is uncommitted**; H1 (Setting key mismatch → panic controls inert), H2 (RBAC: console gated on `is_staff`; money actions not superuser-only), H3 (refund double-credit). See [phase-10-review.md](phase-10-review.md).
- Bugs: M1 export ledger crash (`entry_type`), M4 Customer-360 audit always empty (case mismatch).
- Confirm earlier HIGH fixes applied: Phase 9 H1 (`checkout_key` random → double-charge).
- Golden-path E2E has not been demonstrated live (server boots ≠ cycle proven).
- Pending decision: emoji in notification bodies (Phase 7 M3).

---

## Definition of Done — "one complete cycle" (proposed Phase 9.5: UI & Integration Hardening)

**A. Unified UI shell**
- Single `templates/base.html` (Tailwind + Heroicons + nav + Estalatree branding).
- `storefront`/`dashboard`/`console` bases extend it.
- Override allauth templates under `templates/account/` (`login.html`, `signup.html`, `password_reset*.html`, `email/*`) to extend the shell.

**B. CSS pipeline**
- Tailwind builds to `static/css`; `collectstatic` wired; served locally (not CDN). Confirm `package.json` build runs and output is referenced.

**C. Google SSO (real)**
- Override auth templates to render the provider button.
- Create the `SocialApp` (client id/secret from env).
- Test Google login end-to-end; surface it inline at the checkout login step (ADR-016).

**D. Email verification**
- Decide required vs optional; if required, wire the gate before purchase/top-up.

**E. Seed/demo data**
- Management command: superadmin, one seller, a published StorePage, one product + plan + license_key deliverable, one customer (+ wallet).

**F. Live golden-path E2E (with Duitku sandbox)**
- Browse store → login/SSO → top-up-and-buy → license key issued → activate (API) → device + subscription visible in dashboard → renewal job → reminder. Capture each step.

**G. Close blockers first**
- Phase 10 H1/H2/H3 + M1/M4; confirm Phase 9 H1; emoji decision.

---

## Recommendation
Treat this as a dedicated **Phase 9.5 — UI & Integration Hardening** before Phase 11. The backend cycle is sound; what remains is the "last mile" that makes it a usable product: one styled shell across all surfaces (including auth), real Google SSO in the UI, seed data, and a demonstrated live end-to-end run. Only after F (live E2E green) should the cycle be called 100%.
