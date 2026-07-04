# Phase 1 — Marketplace Landing Page (`/`)

Status: **approved, not yet implemented**. Uses the shared [design system](01-design-system.md).

## What changes

Root `/` currently renders whichever `StorePage` was published first (`apps/storefront/views.py:88-144`, `apps/storefront/urls.py:9`) — a single-merchant leftover. This phase replaces that with a real marketplace homepage. Individual seller pages move to being reachable **only** at `/<slug>/` (already the mechanism, just no longer aliased to root).

Out of scope this phase (explicitly deferred to Phase 2+, see [03-roadmap-future-phases.md](03-roadmap-future-phases.md)): `storefront/base.html` and everything extending it (`page.html`, `product.html`, `checkout.html`, `topup.html`, `order_status.html`, `contact.html`, `terms.html`, `privacy.html`) — those stay pixel-identical to today until their own phase.

## Sections (top to bottom)

1. **Sticky nav** — brand mark (inline SVG logo), "Explore" (anchor-scrolls to the trending section on this same page — no separate catalog/search page exists yet, that's Phase 2+), "Start Selling" CTA → `seller:apply`, "Sign in" / "Sign up" → `account_login` / `account_signup`, wallet balance chip if authenticated (reuse existing `{% wallet_balance %}` templatetag from `apps.core.templatetags.money`). Collapses to a mobile menu below `md`.
2. **Hero** — bold headline + subheadline, dual CTA (primary: browse/explore anchor; secondary: start selling), decorative blob/shape background, trust strip (secure payment, instant delivery).
3. **Trust / social-proof ticker** — pure-CSS marquee strip.
4. **Trending / best-selling products grid** — top public products by paid-order count, tilt-card hover.
5. **How it works** — 3 steps (browse → pay securely → instant access).
6. **Featured sellers** — approved+active sellers with at least one public product, linking to `/<slug>/`.
7. **Value props** — secure wallet/escrow, instant delivery, WhatsApp support, multiple payment methods (Duitku), fair commission.
8. **"Become a seller" CTA banner** — distinctive shaped section, links to `seller:apply`.
9. **Testimonials** — platform-wide published reviews, rating ≥ 4.
10. **FAQ accordion** — small vanilla-JS accordion.
11. **Rich footer** — link columns, legal (`storefront:terms`, `storefront:privacy`), copyright.

All data-driven sections need a graceful **empty state** — today no seed `Product` rows have `seller` set, so trending/featured-sellers can legitimately be empty until real multi-seller data exists.

## Backend changes

- `apps/storefront/urls.py`: repoint `path("", ...)` from `views.page` to a new `views.landing`, **keep `name="page"`** (so the two existing `redirect("storefront:page")` call sites in `views.py` keep working, now correctly bouncing to the marketplace home instead of an arbitrary seller).
- `apps/storefront/views.py`: add `landing(request)` (new queries below); slim `page(request, slug=None)` → `page(request, slug)`, dropping the old "no slug → first published StorePage" fallback branch. `page.html` itself is not touched.

### Queries for `landing()`

Two model constraints verified directly against the code (not assumed):
- `Product.Meta.ordering = ["name"]` — any `.values().annotate(Count(...))` chain on `Product` must call `.order_by()` first, or Django folds `name` into `GROUP BY` and the count degenerates.
- `SellerScopedModel.seller` (`apps/core/models.py`) uses `related_name="+"` — `SellerProfile` has **no reverse accessor** to `Product`. Seller-side aggregation must go through `Product.seller_id` (forward FK) or a `Subquery(OuterRef(...))`.

```python
trending_products = (
    Product.objects.filter(
        visibility=Product.Visibility.PUBLIC,
        seller__is_active=True,
        seller__is_approved=True,
    )
    .select_related("seller")
    .prefetch_related("plans")
    .annotate(paid_order_count=Count(
        "plans__orders",
        filter=Q(plans__orders__status=Order.Status.PAID),
        distinct=True,
    ))
    .order_by("-paid_order_count", "-created_at")[:8]
)

seller_product_count_sq = (
    Product.objects.filter(seller_id=OuterRef("pk"), visibility=Product.Visibility.PUBLIC)
    .order_by()
    .values("seller_id")
    .annotate(cnt=Count("id"))
    .values("cnt")
)
featured_sellers = (
    SellerProfile.objects.filter(is_active=True, is_approved=True)
    .annotate(product_count=Coalesce(Subquery(seller_product_count_sq), 0))
    .filter(product_count__gt=0)
    .order_by("-product_count", "-created_at")[:8]
)

testimonials = (
    ProductReview.objects.filter(
        is_published=True, rating__gte=4,
        product__visibility=Product.Visibility.PUBLIC,
    )
    .select_related("product", "order__customer__user")
    .order_by("-created_at")[:6]
)
```

No new Django app, no new models, no migrations.

## Frontend structure

- `apps/storefront/templates/storefront/landing.html` — extends root `templates/base.html` directly (not `storefront/base.html`, which stays scoped to the narrow single-seller pages this phase). Owns full-width nav/hero/sections/footer. Loads Plus Jakarta Sans via `<link>` in `head_extra`.
- `apps/storefront/templates/storefront/landing/_*.html` — one partial per section (`_nav`, `_hero`, `_trust_ticker`, `_trending`, `_how_it_works`, `_featured_sellers`, `_value_props`, `_seller_cta`, `_testimonials`, `_faq`, `_footer`), included from `landing.html`. Split for reviewability, following the existing `templates/<app>/partials/` convention used elsewhere (dashboard).
- `static/css/input.css` — append (existing `.btn-*`/`.input-field` block untouched): new `@theme` token block (palette + `--font-sans`), a new clearly-commented `@layer components` block for landing-only classes, and a top-level `@keyframes marquee-scroll`. Run `npm run css:build` after changes (`static/css/main.css` is generated, never hand-edited).
- `static/js/site.js` — shared site-wide interactions, loaded with `defer`. Functions: `initScrollReveal()`, `initMagneticButtons()`, `initTiltCards()`, `initCountUp()`, `initMobileNav()`, `initFaqAccordion()`, all gated by the `prefers-reduced-motion` / `pointer: coarse` checks from the design system doc. (Renamed from `landing.js` in Phase 2 once the nav/footer became shared across all storefront pages.)
- `static/icons/favicon.svg` — new hand-crafted brand mark; also inlined (not referenced) inside `_nav.html` for the logo so it can use `currentColor`/hover states.
- `templates/base.html` — one additive `<link rel="icon">` line (applies favicon platform-wide, safe/non-structural).

## Test changes (`tests/test_storefront.py`)

- `test_store_page_returns_200_when_published` → repurpose to assert `reverse("storefront:store_page", args=[store_page.slug])` returns 200 (the "individual seller page still works at its new address" check).
- `test_store_page_no_store_page_renders_gracefully` → delete. Its "coming soon" branch is only reachable via the old root-fallback path, which no longer exists.
- `test_store_page_404_for_unknown_slug` → unchanged.
- New `test_landing_page_returns_200` — smoke test for root `/`.
- New `test_landing_page_shows_trending_product` — builds a `SellerProfile` + public `Product` + `Plan` + PAID `Order` directly (no `SellerProfileFactory` exists yet), asserts the product name appears in the landing response — exercises the real query paths.

## Verification checklist

1. `npm run css:build` — confirm `static/css/main.css` regenerates cleanly.
2. Run the test suite — confirm updated/new `test_storefront.py` tests pass.
3. Manual check in browser: hero → footer render correctly; empty states look intentional (not broken) when no seller data exists; `/<slug>/` for an existing published store still works; mobile width (375px) collapses nav and stacks sections cleanly; `prefers-reduced-motion` softens animation without hiding content.
4. Confirm `storefront/base.html`-based pages (product/checkout/topup/etc.) are pixel-identical to before this phase.
