# Tested Feature Comparison vs Lynk.id (Customer & Seller POV)

**Date:** 2026-06-20 · **Reviewer:** assistant (review + test run; no code changed).
**Method:** ran the full test suite + walked every customer/seller screen at the template/view level (cannot render visually). Compared against Lynk.id's known capabilities.

## Test run
`169 passed, 12 failed, 2 xfailed` (239s). **All 12 failures are stale tests, not feature regressions:**
- **10× console** — `403 == 200/302/404`: console RBAC now requires the **Operator Group** (ADR-017, commit `3f1a06b`); test fixtures still create a plain `is_staff` user. **Fix the fixtures** (add user to Operator group / grant permission).
- **2× storefront** — assertion text changed ("coming soon" / "Confirm purchase" → "Confirm & Pay Rp X"). **Update the assertions.**
- **Action:** CI is red. Update fixtures + assertions so the suite passes again (the recent RBAC/copy changes landed without test updates).

## Minor issues found during the walkthrough
- **Checkout uses an emoji `✓`** ("✓ Coupon applied", `checkout.html`) — violates the no-emoji rule; use an SVG/text. 
- **Seller home "This week" total is broken** (`home.html` ~line 69 concatenates `d.total` strings instead of summing) — renders garbled; compute the sum in the view.
- **Checkout forces top-up-first**: the Confirm button is `disabled` when `shortfall > 0`, so the seamless one-transaction *top-up-and-buy* (ADR-015, present in `checkout.py`) is not reachable from the UI — the buyer must top up separately, then return. Decide: surface true top-up-and-buy, or keep wallet-first (more steps, but clearer).
- **Verify** the purchase email includes the download/access link (BUG-2) — products page BUG-1 is fixed (`payload.download_url`/`access_url`).

---

## Customer POV — feature comparison

Legend: ✓ have · ~ partial · ✗ missing

| Lynk.id capability | Estalatree now | Note |
|---|---|---|
| Link-in-bio store page | ✓ | blocks: product/link/heading/text |
| Product cover image | ✓ | `cover_image_url` added + shown |
| Product card (price + CTA) | ✓ | image + price + Buy |
| Social login | ✓ | Google SSO inline |
| **Direct pay-per-item** | ✗ | wallet model; checkout requires balance (top-up-first) |
| Guest checkout | ✗ | login required |
| Coupon at checkout | ✓ | inline apply + discount preview |
| Trust signals at checkout | ~ | "Secure / Instant / Wallet" strip + method badges (no reviews) |
| Payment methods (VA/QRIS/ewallet/retail) | ~ | shown, but only via top-up (Duitku), not direct |
| Wallet/balance | ✓ | header chip, low-balance badge, quick top-up chips, ledger w/ balance-after |
| Buyer library ("My Purchase") | ✓ | license key copy, seat usage, download/access, reveal-once secrets, delivery instructions |
| **Gated/expiring download** | ✓ | server-gated `/download/...` (commit `7cec4f9`) — better than lynk's raw link |
| File hosting (upload) | ✗ | link-only (paste GDrive/URL) |
| Course player + progress | ✗ | no course product type |
| Invoices / receipts | ~ | invoice numbers added; **PDF unverified** |
| Email delivery of file/link | ~ | verify (BUG-2) |
| Profile security (password/2FA/Google) | ✓ | links added; 2FA via allauth pending |
| Notification preferences | ✓ | added |
| Email verification gate | ✓ | added |
| Support | ~ | WA contact; no ticket trail |
| Footer / legal pages | ✓ | added |
| Reviews / ratings | ✗ | none |
| Cart / multi-item / bundles | ✗ | single-item checkout |
| Mobile-first polish | ~ | responsive, not verified mobile-first |

**Customer verdict:** the buy → pay → receive → manage loop is now genuinely solid and in places **ahead** of lynk.id (gated download, reveal-once secrets, license/seat management, renewal forecast). The remaining gaps are the *paradigm* ones (wallet vs direct-pay, guest checkout) and *product breadth* (course/membership, reviews, cart).

---

## Seller POV — feature comparison

| Lynk.id capability | Estalatree now | Note |
|---|---|---|
| Seller dashboard KPIs | ✓ | revenue / orders / active subs / pending |
| **Revenue chart** | ✓ | 7-day bar chart (new) — closes a big analytics gap |
| New-order alerts | ✓ | animated pending banner |
| Product CRUD | ✓ | + cover image, plans, deliverables |
| Deliverable types | ✓ | download/link/credentials/api_key/manual/license |
| Entitlement management | ✓ | UI added (commit `d784e82`) |
| Store page editor | ✓ | add/remove product & link blocks |
| Appearance / theme editor | ✗ | `theme` JSON unused; no drag-drop/preview |
| Vouchers / coupons | ✓ | CRUD + atomic redemption |
| WhatsApp blast | ~ | async broadcast + segments (basic) |
| Email marketing / automation | ✗ | none |
| Affiliate program | ✗ | none |
| Upsell / order bump / cross-sell | ✗ | none |
| **Payout / withdrawal to bank** | ✗ | single-merchant + wallet model (paradigm) |
| Analytics depth (funnel/sources/date-range) | ~ | 7-day revenue only; no funnel/sources |
| Custom domain / white-label / SEO/OG | ✗ | none |
| Reviews / social proof / sold-count | ✗ | none |
| Seller sale notifications | ~ | dashboard alert only (no push/email digest) |
| Operational (duplicate/import/schedule/preview) | ✗ | basic CRUD |
| Product types (course/membership/event/booking/physical) | ✗ | license/file/link/credential focus |
| Tax / auto-invoice | ~ | invoice numbers; PPN/PDF pending |

**Seller verdict:** the cockpit jumped closer to lynk.id (KPIs + revenue chart + alerts + entitlement UI). The structural distance that remains is **growth tooling** (affiliate, email marketing, upsell), **payout** (different by design), **appearance/page-builder depth**, **richer product types** (course/membership), and **deeper analytics**.

---

## Net comparison

- **Where Estalatree now matches or beats lynk.id:** licensing + seat/device management, prepaid-recurring, gated/expiring downloads, reveal-once secrets, money-rigor + panic controls, checkout clarity (balance-after, shortfall guard), seller revenue chart + entitlement UI.
- **Where it's still clearly behind (ease/detail):** direct pay-per-item simplicity & guest checkout; product breadth (course player, membership, reviews, cart); seller growth suite (affiliate, email, upsell); appearance/page-builder depth; payout (by design); analytics depth.
- **Felt gap closing fastest if prioritized:** appearance/page-builder, richer product cards/types, and (optionally) a true one-action top-up-and-buy or a direct-pay path for casual buyers.

## Immediate cleanups (from this test pass)
1. Fix the 12 stale tests (Operator-group fixtures + checkout copy) → green CI.
2. Remove the `✓` emoji in checkout (no-emoji rule).
3. Fix seller-home "This week" total computation.
4. Decide top-up-and-buy vs wallet-first at checkout; verify purchase email includes the file/link.
