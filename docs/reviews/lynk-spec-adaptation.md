# Lynk.id Spec → Estalatree Adaptation Notes

**Date:** 2026-06-20 · **Author:** assistant (review of user's Lynk.id feature spec).
**Purpose:** map the user's Lynk.id feature spec onto Estalatree — what we **have**, **adapt**, **add**, or deliberately **differ** — given Estalatree's distinct model (prepaid buyer wallet + token licensing + single-merchant, multi-seller-ready). Read Section A first: a 1:1 feature copy would fight our architecture in four places.

---

## A. Key reconciliation principles (paradigm deltas — read first)

1. **"Wallet" means opposite things.** Lynk's wallet = **seller earnings** (withdraw to bank). Estalatree's wallet = **buyer prepaid balance**. Lynk's Module 8 (Earnings/Payout/Withdrawal) has **no single-merchant analog** — the owner keeps 100%, money lands in your own gateway/bank, not a per-seller payout. **Payout only becomes real in the multi-seller stage** (then a seller earnings ledger + withdrawal is needed). Do **not** build seller payout for single-merchant.

2. **Direct-pay vs wallet checkout.** Lynk = pay-per-item directly. Estalatree = top-up-and-buy from balance. Our model is superior for recurring/licensing but heavier for casual buyers. **Decision needed:** keep wallet-first, or add an optional **direct-pay path** (one Duitku invoice per item) for simple one-off products to match Lynk's ease. (Today the checkout even disables Buy until balance covers it — most-friction variant.)

3. **Accounts+licensing vs email-OTP access.** Lynk lets buyers access via **email + OTP** (no full account). Estalatree requires accounts (needed for license/seat/device management). Keep accounts for licensed products, but consider a **lightweight email-link access** for pure file/link products to reduce friction.

4. **No owner tiering (ADR-018).** Lynk's Module 13 (Free vs PRO, 5%/3% fee, watermark, storage caps) **does not apply to the owner** — all features are baseline for you. Free/PRO tiers + transaction fees only re-appear as **seller plans in the multi-seller stage**.

5. **Our architecture already matches their best recommendations.** Their "Block as polymorphic entity" = our `StorePage` + `Block(type, config JSON, position)`. Their "extensible product types" = our `Deliverable` + `Provisioner` registry + `Grant`. So most of this is **extend existing models**, not rebuild. This is the strongest validation of the design.

---

## B. Module-by-module mapping

Legend: **HAVE** · **ADAPT** (exists, extend to our model) · **ADD** (new) · **DIFFER** (intentionally not as Lynk).

| Lynk module | Estalatree now | Action | Note |
|---|---|---|---|
| **1. Auth & Account** | allauth email+Google, email-verify gate, password reset | HAVE | Multi-admin = our Operator Console + RBAC (ADR-017). "Verified-before-monetize" KYC gate → single-merchant: the owner's Duitku setup checklist; multi-seller: `SellerProfile.is_approved` (have, manual). |
| **2. Page builder** | `StorePage` + `Block`; seller store editor (add/remove product+link) | ADAPT | Add: **drag-drop reorder**, per-block **image/title/layout**, **release_time** (scheduling), enable/disable. Block model already has `config JSON` — extend, don't rebuild. |
| **3. Block types** | product, link, heading, text | ADAPT/ADD | Add layouts (Default/Grid/Large/Compact). New types map to deliverables (see §D). |
| **3.2 Digital Product (rich)** | Product(name, cover_image_url, description text) + Plan(price, interval, seat) + Deliverable | ADD fields | Biggest gap — see §C for the field-level list (PWYW, sale price, stock, qty limit, CTA text, add-ons, custom questions, reviews, per-product WA notif, custom email, rich-text, video). |
| **4. Appearance / theming** | `StorePage.avatar_url/title/description`; `theme` JSON **unused** | ADD | Theme editor (banner, profile image, about, color picker, layout variants) + **live mobile preview** (iframe of draft). Use the existing `theme` field. |
| **5. Checkout & payments** | top-up-and-buy, coupon, balance-after, trust strip, method badges | ADAPT | Add **custom fields** ("Question for Customer"), **add-ons/upsell at checkout**, **PWYW**. Decide direct-pay (§A-2). Methods already via Duitku. |
| **6. Marketing suite** | Vouchers (HAVE), WA broadcast (~basic), entitlement UI | ADD | Email marketing, automate-workflow (trigger→action; our `core.events` is the perfect base), affiliate (multi-seller), custom post-purchase message. Clip Campaign → **DIFFER/defer** (off-core UGC marketplace, very large). |
| **7. Order management** | seller Orders, buyer dashboard "My Products", console Customer 360 | HAVE | Add custom-field data display + "resend access" action. |
| **8. Earnings / Payout** | buyer wallet only; owner keeps 100% | DIFFER | **No seller payout for single-merchant.** Multi-seller: add seller earnings ledger + withdrawal (Stage 3). PayMe-style donation link → optional simple free/PWYW product. |
| **9. Analytics** | seller 7-day revenue chart; console KPIs | ADD | Add per-block **views/clicks**, date-range, top products, sales distribution, social clicks. **Differentiator:** add **funnel** (view→click→checkout→paid) — Lynk lacks it (their own note). |
| **10. Member area (buyer)** | dashboard "My Products" (full account) | DIFFER/ADAPT | Keep accounts for licensed products; consider light email-link access for file/link products (§A-3). |
| **11. Settings & admin** | Operator Console + Settings + audit; in-app notif bell **missing** | HAVE/ADD | Add in-app notification bell + Tutorials/knowledge-base. |
| **12. Integrations** | Duitku, WA gateway; file via external URL | ADD | Pixels/GA (Stage 2), **custom domain** (Stage 2/3), **file upload hosting** (currently link-only), per-product webhook/pixel tab. |
| **13. Free vs PRO** | — | DIFFER | N/A for owner (ADR-018); seller plans only if multi-seller. |
| **14. Non-functional** | gated download ✓, scheduling jobs ✓, idempotency ✓, audit ✓ | HAVE/ADD | Add: **auto email file delivery** (verify BUG-2), **file upload + secure hosting**, **reusable rich-text editor**, **live preview engine**, mobile-first pass. |

---

## C. Field-level additions for "Digital Product" (their 3.2 — highest value)

Map onto `Product` / `Plan` / a new `ProductExtras` and `Order`:
- **Rich-text description** (replace plain text) + **preview image gallery** + **preview video URL**.
- **Pricing:** `sale_price` (strikethrough), **pay-what-you-want** (`pwyw` + `min_price`), **currency** (IDR fixed for now).
- **Inventory:** `stock_quantity` (nullable = unlimited), `max_qty_per_checkout`.
- **CTA:** `purchase_button_label` (default "Buy Now").
- **Add-ons / order bumps:** related plans offered at checkout.
- **Custom questions:** `ProductQuestion(label, type, required)` → captured into `Order.custom_fields (JSON)`; Name/Phone toggles enable WA follow-up.
- **Reviews:** `ProductReview(product, buyer, rating, text)` (cap/curate) + sold-count badge.
- **Per-product notifications:** opt-in WA notification (Lynk charges Rp600/txn; for you it's just a toggle), `custom_email_message`.
- **Scheduling:** `release_time` on Block (and/or product).

> Architecture: most of these are **catalog/order-layer** additions; none touch the money/ledger core. Keep them on `Product`/`Plan`/`Order`, not on the provisioning core.

---

## D. New product types via the provisioning layer

Their richer block/product types slot into our `Deliverable` + `Provisioner` pattern — **this is exactly what the extensibility design is for**:

| Lynk type | Estalatree approach | Effort |
|---|---|---|
| Course / e-course | New `Deliverable.type = course` + a **course player** (modules/lessons/video, progress) + provisioner that grants access | High (player UI) |
| Event / ticketing | New `ticket` deliverable + QR code + check-in scan | High |
| Blog / content | A `Block` content type (rich text), gated or free | Low |
| Media kit | A `Block`/page type (rate card, stats) | Low |
| Membership / community | Reuse our **Subscription** model + a `community` access grant | Medium |
| Chat / video call (1:1) | Booking/slot + external meeting link grant | Medium (defer) |
| Physical product | **DIFFER** — needs shipping/address/stock/logistics; off Estalatree's digital/license positioning. Defer or skip. |

---

## E. Estalatree-adapted roadmap (their Fase 1–3 reconciled with our state)

- **Already done** (vs their Fase 1): auth+verify, page builder (link/product), checkout, **gated auto-delivery**, orders, statistics (basic), licensing (our extra). **No payout** (by design).
- **Next (their Fase 2 mapped):** rich digital-product fields (§C: PWYW, sale price, stock, custom questions, add-ons, reviews), **appearance/theme editor + live preview**, **file upload hosting** + verify email delivery, course/e-course (new deliverable + player), custom post-purchase message, member-area polish.
- **Later (their Fase 3 mapped):** email marketing, automate-workflow (on `core.events`), WA blast depth, event/ticketing, pixels/GA/custom domain, **multi-seller activation** (then: affiliate + seller payout + Free/PRO seller plans), **funnel analytics** (differentiator).

---

## F. Differentiation (lean into our strengths, don't just copy Lynk)
1. **Funnel analytics** (view→click→checkout→paid + conversion) — Lynk lacks it; their own note flags it.
2. **Token licensing + seat/device management** — Lynk has none; this is the reason Estalatree exists.
3. **Gated/expiring per-buyer downloads + reveal-once secrets** — already stronger than Lynk's raw links.
4. **Prepaid recurring via balance** — solves Indonesia's no-auto-debit problem Lynk can't.
5. **Owner keeps 100%** (no 5%/3% platform fee) — a positioning advantage to state plainly.

---

## Bottom line
Their spec is a solid parity map, and ~70% of it is **extend-not-rebuild** because our Block + Provisioning models already encode the same polymorphism. Four things must **not** be copied 1:1: seller payout, Free/PRO owner tiering, direct-pay-only checkout, and physical products — each conflicts with Estalatree's model or positioning. Prioritize the **rich digital-product fields**, the **appearance/theme editor + live preview**, **file hosting + email delivery**, and **funnel analytics** — these close the felt gap with Lynk fastest while playing to our architecture.
