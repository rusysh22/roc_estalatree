# Phase 3 — Checkout, Order Status, Top-up

Status: **shipped**. Uses the shared [design system](01-design-system.md); builds on Phase 2's shared `storefront/base.html` shell.

## What changed

`checkout.html`, `order_status.html`, `topup.html` were restyled to the Berlanggan design system (ink/primary/moss/gold tokens, rounded-2xl/full shapes, Jakarta Sans, `landing-card` reuse) with **zero functional changes** — these are the highest-stakes pages (real money, real orders), so this phase was intentionally a pure re-skin:

- Every `name`, `id`, `form="checkout-form"`, `type`, `required`, and `data-*` attribute used by `checkout.html`'s inline duration-calculator script and the `peer`/`sr-only` radio-button pattern was preserved byte-for-byte — only surrounding utility classes changed.
- Color mapping for state semantics: paid/success → `moss`, pending → `gold`, refunded → neutral `ink` (kept visually distinct from both, and distinct from `primary` which is reserved for CTAs/errors so a refund notice doesn't read as an alarm).
- Motion is deliberately restrained here per the design system's own rule ("high-stakes pages... motion should be restrained and purposeful") — only the submit button gets `data-magnetic`, nothing else animates.
- `order_status.html`'s two internal navigation links (`href="/"`, hardcoded) were switched to `{% url 'storefront:page' %}` for correctness — purely a robustness fix, not a design change.

## Verification

- Full test suite re-run: same result as Phase 1/2 (181 passed, 2 xfailed, 1 pre-existing unrelated failure in `test_checkout_get_requires_login`).
- `npm run css:build` re-run after adding `gold-50/100/700/800` tokens (needed for the pending/shortfall notices, which previously used Tailwind's stock `amber-*` scale).
