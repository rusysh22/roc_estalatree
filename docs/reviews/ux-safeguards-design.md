# UX, Flow & Safeguards Design — Estalatree

**Date:** 2026-06-20 · **Author:** assistant (review/design).
**Goal:** make Estalatree's distinctive model (prepaid saldo + token licensing + recurring-via-balance + multi-surface) **easy to understand and hard to get wrong**. Grounded in Nielsen's heuristics: *visibility of status, error prevention, recognition over recall, user control/undo, consistency, help users recover*.

> This is the design foundation. We will fold in the user's deeper Lynk.id analysis to refine specifics (page-builder, card patterns, checkout copy).

---

## 1. The four things that confuse users (and the design answer)

| Confusion | Why it happens | Design answer |
|---|---|---|
| **"Why a balance? Where's my money?"** | Coming from pay-per-item stores; saldo is an extra concept | Always-visible balance (header, done). Checkout uses **one action** "Pay Rp X" (top-up-and-buy behind the scenes). Show **"Balance after: Rp Y"** before confirm. First-time inline explainer: *"Estalatree uses a balance so renewals and repeat buys are 1-tap."* |
| **"I bought it but it doesn't work"** | License/token/activation/seat are technical | Post-purchase **Activate** card front-and-center: copy-key + 3-step guide + download/link. Plain words: **"device"** not "installation fingerprint". Seat shown as **2/3 devices** with "remove a device to free a slot". |
| **"Will I be charged? When?"** | Auto-deduct recurring is invisible | **Renewal forecast**: "Next: Rp X on 20 Jul · balance covers ~3 renewals". Reminders with **one-tap Top-up**. Grace **banner + countdown**. Auto-renew toggle states the consequence. **Never silent suspension.** |
| **"Which dashboard am I in?"** | One account can be customer+seller+operator | **Surface switcher** + distinct surface identity (label/accent per surface). One consistent shell. |
| *(+)* **"I want a cash refund"** | Refund-to-wallet is non-obvious | State **"Refunds go to your Estalatree balance (store credit)"** before purchase and on the refund form. (Ties to ToS / closed-loop ADR.) |

---

## 2. Design principles (the app's spine)

1. **Status-first home.** Each home answers *"what do I have, what's my balance, what needs my attention?"* — surface renew/top-up/activate alerts at the top.
2. **One consistent shell** across storefront/dashboard/console/seller; surface identity always clear.
3. **Progressive disclosure.** Don't explain everything at once — reveal concepts at the moment of need (first-purchase explainer, post-buy activation guide, first-sale seller tips).
4. **Plain language, no jargon.** balance, device, access key, renewal — not fingerprint/grant/entitlement in customer UI.
5. **Recognition over recall.** Show options/states; don't make users remember keys or steps. Copy buttons, saved context.
6. **Visible system status.** Every action has a loading/processing/success/error state (HTMX). Every entity has a status badge + plain meaning + empty-state CTA.
7. **Error prevention before error messages.** Validate inline, disable invalid actions, confirm irreversible ones.

---

## 3. Validation & safeguards ("jagaan") — per critical action

> Pattern: **(a) inline validate → (b) prevent/disable invalid → (c) confirm if irreversible/impactful → (d) idempotent submit → (e) clear result state.**

| Action | Validate | Safeguard / confirm | Status states |
|---|---|---|---|
| **Top-up** | amount numeric; `MIN_TOPUP ≤ amt ≤ MAX_TOPUP` (Setting); suggested chips | — | initiated → **pending (with "Check status")** → credited toast (the webhook safety net, made visible) |
| **Checkout / Buy** | plan active; product visible; coupon valid (inline feedback) | Show **"Pay Rp X · Balance after Rp Y"** before confirm; **disable button on click**; server `checkout_token` idempotency (done) | choosing → processing → **success (key + activate guide)** / payment-pending |
| **Activate (in product)** | key format; key exists; status active; **seat available** | seat_full → guide to **deactivate a device** (self-serve) | active / expired / suspended / seat_full — each with plain copy |
| **Deactivate device** | owns the device | **Confirm: "This frees a seat; the app on that device will stop working."** | active → deactivated (seat freed) |
| **Toggle auto-renew OFF** | — | **Confirm: "Access ends on 20 Jul; we won't auto-charge."** | on/off, with next-charge implication |
| **Reveal secret (credentials/api_key)** | grant active | **Warn before reveal: "Shown once — store it safely."** | hidden → revealed-once → masked |
| **Refund request** | order paid; not already requested | Explain **wallet credit** (not cash); reason required | pending → approved/rejected (notified) |
| **Admin: refund / manual credit / revoke** | superuser-only (done) | **Confirm + reason** (audited); deterministic ref (done) | + AuditLog entry |
| **Coupon apply** | code exists, active, within usage_limit, matches plan | inline "applied −Rp X" / "invalid/expired" | shows discounted price live |

**Cross-cutting safeguards**
- **Idempotency at the UX layer:** disable submit + spinner on every money action; rely on server idempotency as the backstop (checkout_token, ledger `ref`, webhook key) — defends double-click double-charge.
- **Never strand on payment:** explicit *pending* state + "Check status" + background reconciliation (the safety net) must be visible, not just backend.
- **No negative/overdraw paths in UI:** balance-gated actions; server enforces atomically (done).
- **Destructive/irreversible = confirm + consequence text** (device deactivate, cancel renew, reveal-once, admin revoke/refund).
- **Least privilege in UI:** hide actions a role can't perform (operators don't see superuser money actions).

---

## 4. The five flows (with gates & checkpoints)

```
BUY (first time)
 discover → [gate: login/Google SSO inline] → choose plan
   → checkout: validate plan/coupon → show "Pay Rp X, balance after Y"
   → [disable button] submit (idempotent) → processing
   → balance short? → top-up-and-buy (one Duitku invoice) → pending → webhook
   → SUCCESS: show key + Activate guide + download/link → email delivery
```
```
TOP-UP
 amount → [validate MIN/MAX] → Duitku → pending ("Check status") → credited → toast + balance updates
```
```
ACTIVATE (in the OSS product)
 enter key → server validates (exists/active/seat) →
   active → token (heartbeat loop)
   seat_full → "remove a device" deep-link to dashboard
```
```
RENEW (recurring)
 forecast on home → reminder (H-3/H-1, top-up CTA) →
   balance ok → auto-deduct → receipt
   short → GRACE (banner + countdown + top-up CTA) → top-up → instant reactivate / else → suspended (reactivate CTA)
```
```
MOVE DEVICE
 devices list → deactivate (confirm: frees seat) → activate on new device
```

---

## 5. Design-system checklist (to keep it coherent)
- [ ] Status badges: one palette/meaning set (active=green, grace/pending=amber, suspended/failed=red, draft/neutral=gray).
- [ ] Money: always `rupiah` filter; always show **balance-after** on mutations; receipts everywhere.
- [ ] Every list has an **empty state** with the next-action CTA.
- [ ] Every money/destructive button: disabled-on-submit + spinner + confirm-if-irreversible.
- [ ] Plain-language glossary surfaced via tooltips (balance, device, access key, renewal, grace).
- [ ] Consistent shell + surface switcher + surface identity.
- [ ] Mobile-first for storefront/checkout.
- [ ] First-run guides: owner setup (done), buyer first-purchase/activate, seller first-sale.

---

## 6. To incorporate (awaiting user's Lynk.id deep-dive)
Fold in: page-builder/appearance patterns, product-card layout (image/price/CTA/social-proof), checkout copy & payment-method presentation, library/"My Purchase" patterns, and any onboarding/empty-state patterns worth adapting — mapped onto the principles above.

## Bottom line
Estalatree's hard part is conceptual, not technical: saldo + license + recurring are powerful but unfamiliar. Win clarity with **status-first homes, one-action checkout, plain language, always-visible balance/forecast**, and win trust with **error-prevention + confirm-on-irreversible + visible pending/recovery states**. The engine already enforces correctness; this layer makes it *feel* safe and obvious.
