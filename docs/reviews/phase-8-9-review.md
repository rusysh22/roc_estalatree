# Phase 8 & 9 Review — Customer Dashboard + Public Storefront

**Date:** 2026-06-19 · **Reviewer:** assistant (review-only; no code changed)
**Commits reviewed:** `2cc5930` (Phase 8 Dashboard), `4bfb2e0` (Phase 9 Storefront)
**Also confirmed:** `32a1926` applied Phase 7 fixes (WA_TOKEN env, NotificationLog dedup, shortfall-only reminders).
**Verdict:** Access scoping is correct throughout — dashboard views all `@login_required`, queries filtered by `customer`/`license__customer` (no cross-customer leak); storefront public pages are browse-only, checkout/top-up require login. One HIGH (checkout idempotency defeated → double-charge) plus medium storefront items; Phase 8 is solid with minor convention items.

---

## Phase 9 — HIGH

### H1. `checkout_key` uses a per-request random UUID → checkout idempotency defeated → double-charge
In `checkout_plan` (POST): `checkout_key = f"ck:{user.pk}:{plan.pk}:{uuid4().hex[:12]}"`. The Phase 4 idempotency (unique `Order.idempotency_key`) depends on a **stable key per checkout intent**. A fresh UUID per POST means a **double-click on "Buy" creates two Orders and two debits** — the customer is charged twice. This bypasses the very protection that was built.
- **Action:** make the key deterministic per intent — generate an idempotency token once on the checkout GET (hidden field, from session or a signed token), submit it on POST so retries/refresh reuse the same key. (Button-disable + Post/Redirect/Get are complements; server-side idempotency is the required fix.)

---

## Phase 9 — MEDIUM

### M1. Unlisted products are inaccessible
`product_detail` and `checkout_plan` both require `visibility == PUBLIC`. Per spec, `unlisted` = reachable by direct link, only hidden from the catalog. Currently unlisted can be neither viewed nor purchased.
- **Action:** allow `PUBLIC` or `UNLISTED` on product/checkout; block only `DRAFT`.

### M2. Top-up has no min/max validation
`topup` accepts any positive int (Rp1 … absurd amounts).
- **Action:** enforce `MIN_TOPUP` (and a sane max) from `Setting` (was an open question).

### M3. Public contact lead creation has no anti-spam (LOW-MED)
`contact` creates a `Lead` from an anonymous POST with no rate limit/honeypot → spam vector.
- **Action:** add a honeypot field or light rate limiting.

---

## Phase 8 — minor (quality is good)

- **L1.** `deactivate_device` & `toggle_auto_renew` use integer `pk` in the URL — violates the "never expose sequential PKs" convention. Safe from leakage (scoped by `customer`, 404 otherwise) but inconsistent with `refund_request` (uses `public_id`). Consider `public_id`/uuid.
- **L2.** `deactivate_device` mutates `Installation.status` directly in the view rather than via `licensing.deactivate()`. Functionally equivalent + already `log_action`, but two deactivation paths. Consider routing through the service (and recall Phase 5 M1: the device keeps working until token TTL — ensure handled).
- **L3.** Verify HTMX POSTs (`deactivate_device`, `toggle_auto_renew`, `profile`) include the CSRF token (hx-headers or `{% csrf_token %}`) — not visible from the view; check templates.

---

## What's good (keep)
- Dashboard: strict per-customer scoping; renewal forecast (soonest active auto-renew sub + shortfall); self-serve device deactivation scoped + audited; refund request dedup.
- Storefront: anonymous browse + login-gated checkout (inline SSO via allauth redirect); `order_status` scoped to customer; top-up-and-buy redirect flow; contact → Lead → wa.me.

---

## Suggested action mapping
| Item | When |
|------|------|
| H1 deterministic checkout_key | Now (double-charge risk) |
| M1 unlisted accessibility | Now |
| M2 top-up min/max | Now |
| M3 lead anti-spam | Phase 10 / before public launch |
| L1 public_id in URLs | As convenient |
| L2 deactivate via service | With Phase 5 M1 |
| L3 CSRF on HTMX POST | Verify now |
