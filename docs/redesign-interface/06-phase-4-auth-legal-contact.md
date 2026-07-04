# Phase 4 — Auth, Legal Pages, Contact Form

Status: **shipped**. Uses the shared [design system](01-design-system.md).

## What changed

- `templates/allauth/layouts/base.html` / `entrance.html` — this is a *separate* HTML shell from `templates/base.html` (django-allauth's own template-override mechanism), so it needed its own favicon/font/`site.js` wiring rather than inheriting it. `entrance.html` now includes the shared `storefront/partials/_nav.html` instead of its own bare nav, and wraps auth forms in `landing-card` instead of a plain white box — bringing login/signup/logout/password-reset visually in line with the rest of the site.
- `templates/account/{login,signup,logout,password_reset}.html` — pure re-skin. These templates loop over Django form fields dynamically (`{% for field in form %}`, checkbox vs. text branching, error rendering) — every `name`, `id`, `type`, `value`, `autocomplete`, and error-display block was preserved exactly; only the wrapping utility classes changed. Error color reuses `primary` (coral) per the same convention established in Phase 3.
- `apps/storefront/templates/storefront/contact.html` — WhatsApp lead-capture form re-skinned; CTA uses `moss` (matches the "Chat via WhatsApp" green treatment used elsewhere in the product/page templates).
- `apps/storefront/templates/storefront/{terms,privacy}.html` — previously used Tailwind Typography's `prose prose-indigo` classes, but **`@tailwindcss/typography` was never installed** (confirmed via `package.json`), so these classes were silently doing nothing — legal pages were rendering with zero typographic styling. Rewrote both with explicit utility classes (no new dependency added) inside a `landing-card`, fixing a pre-existing (if minor) bug as part of this pass rather than carrying `prose` forward unstyled.

## Verification

- Full test suite: unchanged from Phase 3 (same pre-existing unrelated failure only).
- `npm run css:build` re-run.
- Manual check: login/signup forms submit correctly (field names/ids untouched), Google OAuth button unaffected, error states render in the new color, terms/privacy pages now actually have visible heading/paragraph/list styling.
