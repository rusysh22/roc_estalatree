# Design System — Public Interface

Applies to every phase of the redesign (landing page first, then storefront/product/checkout/etc.). Implemented as Tailwind v4 `@theme` tokens in `static/css/input.css`, additive to the existing generic component classes (`.btn-primary` etc.) used by the seller/console/dashboard tooling — those stay untouched; this system is scoped to the public-identity surfaces only.

## Color palette

Warm and earthy, deliberately not another indigo/blue/purple SaaS gradient. Loosely ties to "growth" (a seller subscribing/growing their business — see the "Berlanggan" name itself, Indonesian for "subscribe").

| Token | Role | Approx. hex (base/500) |
|---|---|---|
| `--color-primary-*` (Ember) | Primary CTA, links, brand accent | `#FF5A36` (coral-orange), full 50–900 scale |
| `--color-ink-*` | Body text, dark section backgrounds — a warm near-black, never pure `#000` | `#16130F` |
| `--color-moss-*` | Secondary accent — success states, "growth" motif, secondary buttons | `#2F7A55` |
| `--color-cream` / `--color-paper` | Page background — replaces `gray-50` on all redesigned surfaces | `#FBF4EC` |
| `--color-gold-*` | Highlight accent — badges, star ratings, small emphasis | `#FFC24B` |

Each gets a 50–900 Tailwind-style scale so it composes with existing utility patterns (`bg-primary-600`, `text-ink-900`, etc.).

## Typography

**Single type family: Plus Jakarta Sans**, used for both display/headings and body/UI text — no serif pairing. Hierarchy is carried by weight and size, not by mixing font families:

- Headings / display: Plus Jakarta Sans **ExtraBold (800)** or **Bold (700)**
- Subheadings / emphasis: Plus Jakarta Sans **SemiBold (600)**
- Body / UI text: Plus Jakarta Sans **Regular (400)** / **Medium (500)**

Loaded via Google Fonts `<link>` (variable font, `wght` axis) scoped to the pages being redesigned (not forced globally onto seller/console/dashboard tooling in this phase). Tailwind token: `--font-sans` set to `"Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif`.

## Shape language

- Large border-radii as the default, not the exception: cards `rounded-2xl`/`rounded-3xl`, buttons pill or `rounded-xl`.
- Organic "blob" decorative shapes for hero/section backgrounds (CSS `border-radius` trick, e.g. `63% 37% 54% 46% / 43% 37% 63% 57%`, or `clip-path`) — used sparingly as background accents, not on interactive elements.
- Asymmetric card corners on product/seller cards (one corner sharper) for a "sticker" feel rather than uniform rounded rectangles everywhere.
- Shadows are soft and color-tinted (e.g. `box-shadow: 0 20px 40px -20px rgba(255,90,54,.35)`), never flat gray.

## Motion & interaction principles

No new JS dependencies (no GSAP/AOS/Framer/etc.) — vanilla CSS + vanilla JS, consistent with the project's existing minimal-dependency approach (only `htmx` exists today, and only in authenticated areas, not the public surfaces).

- **Scroll reveal**: `IntersectionObserver`-driven, staggered fade+rise on section entry — not the default AOS-style "fade up 20px" everyone's seen; combine with slight scale or clip-path reveal for a distinct feel.
- **Marquee / ticker**: pure CSS `@keyframes` infinite scroll, pausable on hover — used for social-proof/activity strips, not for logos-wall clichés.
- **Magnetic buttons**: primary CTAs subtly track the cursor within a small radius (`mousemove` → `translate()`).
- **Tilt cards**: product/seller cards get a subtle `rotateX/rotateY` on hover via `mousemove`, capped to a small angle — not a full 3D flip.
- **Count-up stats**: `IntersectionObserver`-gated, `requestAnimationFrame`-driven numeric count-up.
- **Accessibility is non-negotiable**: everything above is gated behind `matchMedia('(prefers-reduced-motion: reduce)')` (soften/disable) and `matchMedia('(pointer: coarse)')` (disable mouse-tracking effects on touch — content still reveals, just without the animated transition).

## Iconography

Per `docs/CONVENTIONS.md` (binding, unchanged by this redesign): **no emoji as UI icons**. Inline SVG only, Heroicons-style (matches existing icon usage in `product.html`/`page.html`). A small hand-crafted brand mark (SVG) is used as both favicon and nav logo.

## Language

Per `docs/CONVENTIONS.md`: **English UI copy**, confirmed with the user for this redesign (Indonesian localization is a documented future step via Django i18n, not done ad hoc per-page).

## Responsive rules

- Design mobile-first for every new section; verify at minimum 375px, 768px, and 1280px widths.
- Heavy interaction (tilt, magnetic buttons, cursor effects) is desktop-only (`pointer: fine`) — mobile gets clean, fast, simplified transitions instead of a degraded version of the desktop effect.
- Sticky nav collapses to a mobile menu (hamburger or bottom-safe compact bar) below `md`.
