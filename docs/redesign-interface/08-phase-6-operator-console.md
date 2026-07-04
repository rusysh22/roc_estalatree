# Phase 6 — Operator Console (`/console/`)

Status: **shipped**. Explicitly out of scope in the original roadmap (internal admin/operator tool, not public brand identity) — added at the user's explicit request after Phase 5.

## What changed

Unlike the buyer dashboard, the console keeps a **deliberately distinct dark admin aesthetic** (navy `bg-ink-900` top nav + light `bg-cream` content area) rather than adopting the light/cream chrome used everywhere else — this differentiates "you are in an internal tool" from the public/buyer surfaces, which is a reasonable and intentional choice for an operator console, not an oversight. Colors still map onto the same design-system tokens (`ink`/`primary`/`moss`/`gold`) instead of leftover `gray`/`indigo`/`red`/`green`/`amber`.

- `apps/console/templates/console/base.html` — nav and mobile drawer restyled. **Also fixed the same latent mobile-drawer bug found and fixed in Phase 5's dashboard**: the backdrop and drawer panel were nested inside a wrapper `<div>` that was the actual sibling of the toggle checkbox, so Tailwind's `peer-checked:` (which only matches direct siblings via the CSS `~` combinator) silently never reached them. Flattened the structure so both are direct siblings of the checkbox, exactly as done for the dashboard. Also swapped the checkbox from `hidden` (display:none) to `sr-only` for the same robustness reason.
- 8 content templates (`cockpit.html`, `customer_list.html`, `customer_360.html`, `lead_detail.html`, `refund_detail.html`, `audit_log.html`, `settings.html`, `setup.html`) re-skinned with the same color/shape mapping used throughout: `indigo→primary`, `gray→ink`, `green→moss`, `amber→gold`, `red→primary`, cards `rounded-2xl border-ink-100`, pill buttons.
- Confirmed console templates never used the shared `.btn-primary`/`.input-field`/etc. component classes in `static/css/input.css` (same as dashboard) — so this reskin, like Phase 5, has zero risk of leaking into `apps/seller/`, which still shares those same component classes and remains untouched/out of scope unless separately requested.

## Verification

- `npm run css:build` re-run.
- Mobile drawer fix verified the same way as Phase 5: a real CDP-simulated mouse click test confirming the drawer's rect moves from off-screen to on-screen, not just a `.checked` boolean check.
- Did **not** run the full pytest suite for this verification pass — `tests/conftest.py`'s `django_db_setup` no-op means local test runs hit the real dev database directly (see project memory / conversation record), and re-running it would risk wiping seed data again mid-session. Recommend fixing that conftest gap before the next full-suite run.
