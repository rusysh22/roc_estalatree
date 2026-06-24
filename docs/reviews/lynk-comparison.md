# Estalatree vs Lynk.id — Gap Analysis (Seller & User POV)

**Date:** 2026-06-20 · **Reviewer:** assistant (review-only).
**Lens:** judged on **ease-of-use** and **detail/polish**, gap-focused. "It exists" is not a pass — depth and UX count. Severity = how far below lynk.id's standard: **▲▲▲ big** · **▲▲ moderate** · **▲ minor**.

> Fairness first — where Estalatree is genuinely *ahead/different* (lynk.id has none of these): token **licensing + online activation + seat/device management**; **prepaid recurring via saldo** (solves Indonesia's no-auto-debit problem); generalized provisioning (license/credentials/api_key/download/link); immutable-ledger money rigor + panic controls; multi-surface RBAC + Operator Console + Customer 360; owner keeps 100% (no platform 5% fee / withdrawal fee). These are real moats. The rest of this doc is deliberately about the gaps.

---

## A. Seller POV (the creator running a store)

| Capability | Lynk.id depth | Estalatree now | Gap |
|---|---|---|---|
| **Page builder / Appearance** | Rich theme editor (colors, fonts, button styles, avatar, cover, social icons), drag-drop block reorder, live mobile preview, many block types | `StorePage` + `Block` (product + link only); `theme` JSON unused; no editor, no drag-drop, no preview | ▲▲▲ |
| **Product type breadth** | Digital download, **e-course (multi-lesson video player + progress)**, membership, event/webinar ticket, booking/appointment, physical, donation/tip | License-centric + download/link/credentials/api_key; **no course player, no membership, no events/booking** | ▲▲▲ |
| **Payments & payout** | Many methods (VA, OVO/DANA/GoPay/ShopeePay, QRIS, **card, paylater**, retail) + **bank payout/withdrawal** + earnings dashboard | Duitku **top-up only**; prepaid wallet; **no seller payout** (single-merchant), no card/paylater | ▲▲▲ (paradigm) |
| **Affiliate program** | Recruit affiliates, commission %, tracked links, payouts | None | ▲▲▲ |
| **Email marketing / automation** | Campaigns, broadcasts, drip/automation, abandoned-cart | None | ▲▲▲ |
| **WhatsApp blast** | Templated blasts, segments, scheduling | Basic async broadcast (just added) | ▲▲ |
| **Order bump / upsell / cross-sell** | At checkout + post-purchase | None | ▲▲ |
| **Analytics / Statistics** | Views/clicks per link, funnels, traffic sources, revenue charts, date ranges, top products | Seller home: revenue + counts only; no charts/funnels/sources/date-range | ▲▲▲ |
| **CRM / segments** | Buyer list, segments, history, targeted broadcast | Thin seller-side; segments exist in broadcast only | ▲▲ |
| **Custom domain / white-label / SEO** | Custom domain, remove branding, OG/social preview, QR | None | ▲▲ |
| **Social proof** | Ratings, reviews, testimonials, sold-count badges | None | ▲▲ |
| **Seller notifications** | Sale alerts (WA/email/push), daily summary | None for seller | ▲▲ |
| **Operational polish** | Duplicate product, bulk import, schedule publish, draft preview, templates | Basic CRUD | ▲▲ |
| **Tax / auto-invoice** | Automated invoice + tax | Pending (no PDF/PPN yet) | ▲▲ |

## B. User POV (the buyer)

| Capability | Lynk.id depth | Estalatree now | Gap |
|---|---|---|---|
| **Checkout simplicity** | **Just pay for this item** — one-page, many methods, no wallet concept | **Prepaid wallet**: must have/top-up saldo (mitigated by top-up-and-buy, but heavier mental model for one-off buyers) | ▲▲▲ (by design) |
| **Payment methods** | Cards, paylater, all e-wallets, QRIS, retail | Duitku set; no card/paylater | ▲▲ |
| **Guest checkout** | Buy with email only (no account for simple items) | Login required at checkout | ▲▲ |
| **Buyer library / access** | "My Purchase" with re-download, **course player + lesson progress**, magic-link access | Dashboard Products: license key + reveal/copy; download basic; **no course player** | ▲▲▲ |
| **Mobile-first polish** | Link-in-bio is mobile-native, thumb-friendly | Tailwind responsive but desktop-oriented (`max-w` containers); not verified mobile-first | ▲▲ |
| **Language** | **Full Bahasa Indonesia** | **English** — **ACCEPTED trade-off** (user decision 2026-06-20: keep English, no i18n). Gap acknowledged, not actioned. | — |
| **Trust at point of sale** | Reviews, secure-payment badges, refund policy, seller profile | Minimal | ▲▲ |
| **Receipts / invoice** | Email receipt + invoice | Pending (no PDF) | ▲▲ |
| **Support** | In-app/help + WA | WA number only, no ticket trail | ▲▲ |
| **Discovery / store cards** | Polished product cards (price, image, CTA, sold-count) | Basic blocks, limited styling | ▲▲ |
| **Cart / multi-item** | Cart + bundles | Single-item checkout | ▲ |

---

## C. The three deltas that matter most

1. **Wallet vs direct-pay (User ease).** Estalatree's prepaid saldo is *superior* for recurring/licensing but *heavier* for a casual one-off buyer than lynk's "just pay." Top-up-and-buy narrows it, but the wallet mental model + login wall still loses casual-purchase simplicity. **Trade-off, not a bug — but be honest it costs first-purchase ease.**
2. **Bahasa Indonesia (User trust).** lynk.id speaks the buyer's language end-to-end. Estalatree's English-only checkout is a real conversion/trust gap for the Indonesian mass market. The i18n hook exists (deferred) — for a consumer storefront this should be pulled forward.
3. **Page builder + analytics + marketing suite (Seller pull).** This is *why creators pick lynk.id*: a delightful page editor, real analytics, and built-in growth tools (affiliate/email/upsell). Estalatree's seller surface is functional CRUD, not a creator product yet.

## D. To credibly rival lynk.id (priority for parity)

**P1 — biggest ease/trust wins**
1. ~~Bahasa Indonesia UI~~ — **declined** (user: keep English standard).
2. **Appearance/page-builder**: theme editor + drag-drop blocks + mobile preview; richer block/card styling.
3. **Buyer library polish**: re-download, receipts/invoice email, and (if selling courses) a lesson player.
4. **Checkout ease**: more payment methods via Duitku (e-wallets/QRIS/retail surfaced), and consider an optional **direct-pay** path for one-off products to remove the wallet step for casual buyers.

**P2 — seller growth tools**
5. **Analytics**: per-link/product views→clicks→sales funnel, revenue charts, date ranges, traffic sources.
6. **Affiliate program** + **email campaigns/automation** + **order bump/upsell**.
7. Custom domain + white-label + OG/SEO; ratings/reviews/social proof; seller sale notifications.

**P3 — operational**
8. Duplicate/import/schedule/preview; cart/bundles; tax/auto-invoice (overlaps B-7).

---

## E. Bottom line
Estalatree **out-classes lynk.id on the licensing/recurring engine and money rigor** — that's its reason to exist. But measured purely on *consumer ease* and *creator delight*, it is **not yet at lynk.id's level**: the storefront is a functional catalog, not a polished page-builder; analytics and marketing tools are thin; and two consumer fundamentals — **Bahasa Indonesia** and **frictionless pay** — are weaker. None of this is architectural debt; it's product surface + localization. Prioritize Indonesian UI, the page-builder/appearance, buyer-library polish, and broader payment methods to close the felt gap fastest.
