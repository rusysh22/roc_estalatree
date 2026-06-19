# 22 — Feature Catalog (Lynk.id PRO → Estalatree, all-access)

> **Principle:** Estalatree is single-merchant — **you are the owner, so there is no "Upgrade to PRO" for yourself.** Every Lynk.id PRO capability is treated as **baseline / all-access** (no paywall, no caps). They are scheduled across product stages by *effort*, not by tier.
>
> Tiering returns only in the **multi-seller** future (Stage 3): these same capabilities become *Seller* subscription perks, and the marketplace economics (transaction/withdrawal fees) switch on. None of that applies to the owner.

## Link-in-bio

| Lynk.id PRO | Estalatree | Stage | Surface/app |
|-------------|------------|-------|-------------|
| Unlimited links | Unlimited blocks/links (**no caps**) | MVP | storefront |
| Analytics | Built-in views/clicks analytics | Stage 1 | storefront + console |
| Custom domain | Map your own domain to the StorePage | Stage 2 | storefront |
| Custom appearance | Themes / Appearance editor | Stage 2 | storefront |
| Remove Lynk logo | White-label (no forced platform logo) | Baseline (owner) | storefront |
| Additional pages | Multiple StorePages / sub-pages | Stage 2 | storefront |
| Public affiliate links | Affiliate program | Stage 2–3 | marketing |

## Store-in-bio (commerce + content)

| Lynk.id PRO | Estalatree | Stage | Surface/app |
|-------------|------------|-------|-------------|
| E-course video (480 min) | Course product/block + video hosting (**no minute cap**) | Stage 2 | catalog + storefront |
| Questionnaire (20 Gb) | Form/questionnaire block + storage (**no GB cap**) | Stage 2 | storefront |
| Meta pixel tracking | Meta Pixel integration | Stage 2 | storefront + marketing |
| Google Analytics, Meta text | Analytics integrations (GA, Meta) | Stage 2 | storefront + marketing |
| WhatsApp broadcast | WA broadcast (reuses our WA gateway) | Stage 2 | notifications + marketing |

## Marketplace economics — multi-seller only (Stage 3)

> Not applicable to the single-merchant owner. Listed so the model is ready.

| Lynk.id PRO | Estalatree | Stage |
|-------------|------------|-------|
| Transaction fee (3%) | Platform commission per sale (config in `Setting`) | Stage 3 |
| Withdrawal fee (FREE/Rp5k) | Seller payout fee | Stage 3 |

## Dependencies & notes
- **Course video** and **form storage** require object storage (e.g. S3-compatible) and possibly video handling — flag as infra dependency for Stage 2.
- **Custom domain** needs domain verification + TLS automation.
- **Pixels / GA** are injected into StorePage/product pages; respect privacy/consent.
- All of these enrich the **Storefront** ([20-ui-information-architecture.md](20-ui-information-architecture.md)) and **Marketing tools** ([09-features.md](09-features.md)); stage placement aligns with [18-product-evolution.md](18-product-evolution.md).
- **No caps for the owner**: link/minute/GB limits were Lynk's monetization levers, not ours.
