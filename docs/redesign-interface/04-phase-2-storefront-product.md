# Phase 2 — Seller Storefront (`/<slug>/`) + Product Detail (`/p/<slug>/`)

Status: **approved, executing**. Uses the shared [design system](01-design-system.md). Builds directly on Phase 1's nav/footer/theme work.

## What changes

`apps/storefront/templates/storefront/base.html` — the shared shell for `page.html`, `product.html`, `checkout.html`, `topup.html`, `order_status.html`, `contact.html`, `terms.html`, `privacy.html` — is currently a narrow (`max-w-3xl`), indigo-themed leftover from the single-merchant MVP. This phase:

1. Extracts the landing page's nav and footer into **shared partials** (`apps/storefront/templates/storefront/partials/_nav.html`, `_footer.html`) so the whole public site shares one nav/footer implementation instead of two drifting copies. Landing-page-only anchor links (`#trending`, `#how-it-works`, `#sellers`) become absolute links back to the landing page (`{% url 'storefront:page' %}#trending`) so they work correctly from any page, not just the landing page itself.
2. Redesigns `storefront/base.html` to use those shared partials, cream background, Jakarta Sans, and a wider container — bringing consistent nav/footer/typography to **every** page under it immediately. Pages not yet redesigned this phase (`checkout.html`, `topup.html`, `order_status.html`, `contact.html`, `terms.html`, `privacy.html`) keep their existing inner content/markup untouched — only the shared shell around them changes. Their own content redesign is Phase 3/4 (see [03-roadmap-future-phases.md](03-roadmap-future-phases.md)).
3. Redesigns `page.html` (an individual seller's public storefront) with the new design system.
4. Redesigns `product.html` (product detail + checkout entry point) with the new design system.

## Constraint that must be preserved: per-seller theming

`page.html` already supports **seller-chosen customization** via `StorePage.theme` (a JSONField): `primary_color`, `background_color`, `button_style` (`pill`/`square`/default → corner radius), `layout` (`grid`/`compact`/default spacing), `banner_url`, plus social links (Instagram/TikTok/YouTube/Twitter/website). This is real seller-facing functionality, not decoration — it must keep working exactly as before. The redesign wraps this system in the new visual language (cards, shapes, motion) without removing or hard-coding over a seller's chosen `primary_color`/shape/layout. The existing `--color-primary`/`--color-bg`/`.theme-btn-shape`/`.theme-card-shape` CSS custom-property mechanism in `page.html` stays; only the surrounding chrome (nav, footer, page background default, typography, spacing rhythm) gets the Berlanggan design system treatment.

## Buyer-POV priorities (per original request: think like the buyer)

- **Seller page**: fastest path from landing on a creator's page to understanding what they sell and picking a product — avatar/name/trust signals up top, products immediately scannable, no dead ends.
- **Product page**: fastest path from "what is this" to "I trust this enough to pay" — plan comparison must be scannable in one glance, seller identity and trust badges visible without excessive scrolling, reviews close to the decision point, mobile checkout CTA always reachable (sticky or high on the page).

## Frontend structure

- `apps/storefront/templates/storefront/partials/_nav.html` — moved from `landing/_nav.html`, links use full URLs (no bare page-relative anchors), works identically whether rendered on the landing page or any storefront page.
- `apps/storefront/templates/storefront/partials/_footer.html` — moved from `landing/_footer.html`, same treatment.
- `apps/storefront/templates/storefront/landing.html` — updated to include the new shared partial paths instead of its own copies.
- `apps/storefront/templates/storefront/base.html` — rebuilt: shared nav/footer partials, `bg-cream`, Jakarta Sans font stack, wider `max-w-6xl`-class content container (still comfortably readable, wider than the old `max-w-3xl` link-in-bio constraint), cookie banner restyled to match.
- `apps/storefront/templates/storefront/page.html` — redesigned card/shape/type treatment for header, blocks (product/link/heading/text), keeping the existing theme-override mechanism intact.
- `apps/storefront/templates/storefront/product.html` — redesigned hero, plan cards/rows, reviews, sidebar trust content.

## Test impact

Existing storefront tests assert only status codes and presence of specific text/names (no CSS class assertions), so no test changes are required for this phase — verified by re-reading `tests/test_storefront.py` before starting.

## Verification checklist

1. `npm run css:build` after any new CSS additions.
2. Run `tests/test_storefront.py` — should pass unchanged.
3. Manual check: landing page nav/footer unaffected in behavior (links still resolve); an existing published seller page renders with the new chrome and still honors a custom `theme.primary_color`/`button_style` if set; product page shows plans/reviews/sidebar correctly; checkout/topup/etc. pages still function (only chrome changed, not logic).
4. Mobile width check on both redesigned templates.
