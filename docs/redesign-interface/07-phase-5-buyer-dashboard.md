# Phase 5 — Buyer Dashboard

Status: **shipped**. Uses the shared [design system](01-design-system.md).

## What changed

Full visual re-skin of `apps/dashboard/templates/dashboard/` — the buyer's post-login area (home, wallet/ledger, products, subscriptions, devices, invoices, profile, support, course player). Originally scoped as optional/lower-priority (post-login utility, not identity-forming for a new visitor), but the user asked for the full pass rather than shell-only.

- `apps/dashboard/templates/dashboard/base.html` — nav (desktop bar + mobile slide-in drawer), footer, and body background/font brought in line with the rest of the site. This nav is *not* the same shared partial used by `storefront/partials/_nav.html` (different link set: Products/Subscriptions/Devices/Invoices/Profile/Support, wallet chip, seller/console cross-links, htmx headers) — it's a parallel implementation restyled to match.
- All 12 content templates + 4 htmx-partial fragments (`ledger_rows.html`, `device_row.html`, `auto_renew_toggle.html`, `secret_revealed.html`) re-skinned to the same color/shape system as the rest of the app: card containers use plain `bg-white border border-ink-100 rounded-2xl` (not `.landing-card` — that asymmetric decorative shape is reserved for marketing pages; dashboard is dense utility UI), buttons go pill-shaped (`rounded-full`), and the same color mapping used everywhere else (`indigo→primary`, `gray→ink`, `green→moss`, `amber→gold`, `red→primary`).
- **Zero functional changes** — every `hx-get`/`hx-post`/`hx-target`/`hx-swap`/`hx-confirm`, `id` (several are live htmx swap targets, e.g. `id="device-{{ pk }}"`), form field `name`/`type`/`value`/`required`, and Django template logic was preserved exactly. This mattered more here than anywhere else in the redesign since the dashboard is the most htmx-dependent surface in the app — a renamed `id` or dropped `hx-target` would silently break a live swap.
- `static/css/input.css`'s shared `.btn-primary`/`.btn-secondary`/`.btn-danger`/`.input-field` component classes (used by `apps/seller/` and `apps/console/`, both explicitly out of scope) were **not touched** — dashboard templates already used inline Tailwind utilities directly, not those shared classes, so there was no risk of the redesign leaking into the seller/operator tooling.

## Verification

- `npm run css:build` re-run.
- Full test suite re-run: same result as every prior phase (pre-existing unrelated `test_checkout_get_requires_login` failure only).
- Manual check: htmx-driven interactions (device deactivate, ledger pagination/swap, auto-renew toggle, secret reveal) still function — verified by exercising each in a running dev server, not just visually inspecting the markup.
