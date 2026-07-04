# Roadmap — Phases After the Landing Page

Not yet detailed to implementation level — recorded here so the overall direction is visible while Phase 1 ships. Each phase gets its own detailed spec doc (like [02-phase-1-landing-page.md](02-phase-1-landing-page.md)) written and approved before that phase's code starts.

## Phase 2 — Individual seller storefront + product detail page

- `apps/storefront/templates/storefront/page.html` (`/<slug>/`, a seller's own link-in-bio page) and `apps/storefront/templates/storefront/product.html` (`/p/<slug>/`) get the full design-system treatment (colors, type, shape, motion from [01-design-system.md](01-design-system.md)).
- `storefront/base.html` (currently a narrow `max-w-3xl` shell shared by page/product/checkout/topup/etc.) likely needs to be widened and re-themed — at that point the landing page's nav/footer partials (built in Phase 1) should be evaluated for reuse here instead of staying landing-only, to avoid duplicate nav/footer implementations drifting apart.
- Buyer-POV priorities to design for: fastest path from "see a product" to "understand what I'm buying" to "pay" — plan comparison clarity, seller trust signals (surfaced prominently, not buried in a sidebar), review/social proof placement.
- Consider whether `Product` needs a lightweight category/tag field at this point (none exists today) if a real "browse all products" page (not just the landing page's trending strip) becomes necessary.

## Phase 3 — Checkout, order status, top-up

- `checkout.html`, `order_status.html`, `topup.html` — currently functional but visually generic (plain white cards, indigo buttons). Redesign for confidence-at-the-moment-of-payment: clear price breakdown, duration/coupon UI, wallet balance state, payment method clarity.
- These are the highest-stakes pages (money changing hands) — motion/animation here should be restrained and purposeful (state transitions, confirmation feedback), not decorative.

## Phase 4 — Auth + legal + contact

- `templates/account/*.html` (login/signup/password reset), `templates/allauth/layouts/*.html`, `storefront/terms.html`, `storefront/privacy.html`, `storefront/contact.html` — bring into the same visual system so the whole public journey feels like one product, not a redesigned homepage bolted onto an old shell.

## Phase 5 — Buyer dashboard visual pass

- `apps/dashboard/*` — lower priority since it's post-login/utility, not identity-forming for a new visitor. Visual consistency pass only (colors/type/shape), not a UX rethink, unless issues surface.

## Explicitly out of scope (unless separately requested)

- `apps/seller/*` (seller console) and `apps/console/*` (operator admin console) — internal tools, not part of the public brand identity.
- Any new Django app, model, or migration — this redesign is visual/template/routing-level; if a phase turns out to need new data (e.g. product categories), that's a separate decision to raise explicitly before implementing.
