# Mobile & Responsive Review — Customer / Seller / Super Admin

**Date:** 2026-06-20 · **Reviewer:** assistant (review-only; no code changed). Mobile viewport ~400px.
**Ask:** responsive across all three surfaces, and **delight the customer** (mobile-first).

## Positives (keep)
- Root `templates/base.html` has the viewport meta.
- **Surface switcher** now present (Dashboard/Console/Seller links via `user_surfaces`) — closes deep-eval H-6.
- Customer dashboard content **stacks to a single column** on mobile (cards read well).
- Seller tables use `overflow-x-auto` (scroll, not clip).

---

## BUG (P1) — corrupted em-dash (mojibake)
The screenshot shows **"Team â€" Rp499.000"** — an em-dash `—` saved as double-encoded bytes. Present in **7 files**: `dashboard/home.html`, `console/{customer_list,customer_360,refund_detail,cockpit}.html`, `dashboard/profile.html`, `seller/vouchers.html`.
- **Fix:** replace the corrupted sequence with the HTML entity **`&mdash;`** (or `&#8212;`), and ensure files are saved **UTF-8**. Entities are encoding-proof.
- **AC:** renders as "Team — Rp499.000".

---

## Responsiveness per surface

### 1. Customer Dashboard — **priority** (P1)
- **Header nav overflows on mobile** (screenshot: "Products Subscriptions Devi…" clipped). It's a flat flex row of brand + balance chip + 7 links + Sign out — no collapse. 
- **Fix:** on mobile, collapse the nav into a **hamburger drawer**, or better for a consumer app, a **bottom tab bar** (Wallet · Products · Subscriptions · Profile) — thumb-reachable, app-like.
- Content cards are fine (single column).

### 2. Seller Dashboard — **broken on mobile** (P1)
- Fixed **`w-60` sidebar is always visible** (`flex` + `aside w-60 flex-shrink-0`); on a 400px screen it eats 240px, leaving ~160px — unusable. No collapse.
- **Fix:** `hidden md:flex` on the sidebar + a **mobile top bar with a hamburger** that opens the sidebar as an off-canvas drawer (HTMX/Alpine or a CSS checkbox toggle). Tables already scroll.

### 3. Console (Super Admin / Operator) — desktop-primary (P2)
- Top nav is a flat flex row (~7 links) → overflows on mobile; no hamburger.
- **Console tables have no `overflow-x-auto`** (only seller does) → wide tables (cockpit, customer_360, audit, customer_list) overflow the page horizontally on mobile.
- **Fix:** wrap every console table in `overflow-x-auto`; collapse the nav into a hamburger. Lower priority (admins use desktop), but should not break.

---

## "Memanjakan customer" — mobile-first patterns (P1, customer surface)
1. **Bottom tab bar** on mobile (Wallet/Products/Subscriptions/Profile) + a persistent **balance + Top-up** affordance — the saldo is the heart of the product; keep it one tap away.
2. **Sticky primary CTA** per screen (e.g., "Top up", "Buy", "Activate") within thumb reach.
3. **Touch targets ≥ 44px**; generous spacing; large tap areas on cards/buttons.
4. **Tables → card lists on mobile.** The ledger/transaction table should render as stacked card rows under `sm` (date + amount + balance-after per card) instead of a horizontally-scrolling table.
5. **Status-first home** (already close): balance, next renewal, what-needs-attention at the top — keep alerts (low balance / grace) as full-width banners on mobile.
6. **Fast, no-reload** interactions (HTMX partials) — already the pattern; keep payloads small.
7. **One-hand reachability:** primary actions bottom-anchored, secondary up top.

---

## Priority
| # | Item | Sev |
|---|------|-----|
| 1 | Fix em-dash mojibake (7 files) | P1 |
| 2 | Customer dashboard: responsive nav (hamburger or bottom-tab) | P1 |
| 3 | Seller dashboard: collapse sidebar (`hidden md:flex` + drawer) | P1 |
| 4 | Customer: ledger table → card list on mobile; sticky balance/CTA; 44px targets | P1 (delight) |
| 5 | Console: `overflow-x-auto` on tables + hamburger nav | P2 |

## Bottom line
The desktop UI is solid and the surface switcher/viewport are in place, but **mobile is not done**: the seller sidebar doesn't collapse (broken), both customer and console navs overflow, and an em-dash encoding bug is visible. For "memanjakan customer," go beyond making it merely fit — add a **bottom tab bar + sticky balance/CTA + card-list tables** on the customer surface. Customer-first, then seller, then console.
