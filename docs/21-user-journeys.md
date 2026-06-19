# 21 — User Journeys (A–Z, Connected)

> End-to-end journeys per persona, verified to connect step-to-step. The **Customer** journey is the priority: fewest steps, never surprise, one-tap to resolve, self-serve everything.

## Customer-first principles
1. **No dead ends** — every state has an obvious next action.
2. **Never surprise** — no silent suspension; always forewarned with a one-tap fix.
3. **Self-serve by default** — device swap, renewal, invoices, refund request: no support ticket needed.
4. **Pay the funding step once** — the balance model trades one upfront top-up for frictionless repeat & recurring.

---

## A. Customer / User journey (priority)

| # | Step | Connects to | Friction-reducer (must-have) |
|---|------|-------------|------------------------------|
| 1 | **Discover** on shared StorePage | storefront | Browse without login. |
| 2 | **Buy** clicked | checkout | **Inline Google SSO (1-click)** — no separate signup wall. |
| 3 | **Fund + pay** | wallet + Duitku | **Top-up-and-buy is the default**: if balance short, one Duitku transaction funds the exact (or suggested) amount **and** completes the purchase. Returning customers with balance → instant buy. |
| 4 | **Payment confirm** | webhook | If webhook lags: show **pending** state + auto-retry + "check status" button (never leave the customer stranded). |
| 5 | **Receive** | provisioning/grant | Immediately: **copy license key (1-click) + activation guide + download** + WA/email with the key. |
| 6 | **Activate** in product | activation API | On failure (seat full/typo): clear error → link to dashboard Devices. |
| 7 | **Use** | heartbeat | Invisible; product validates in the background. |
| 8 | **Renewal** (recurring) | subscription job | **Forecast** on dashboard + **reminders H-3/H-1 with a top-up button** + grace banner w/ countdown → top-up → **instant reactivation**. |
| 9 | **Swap device** | deactivate endpoint | Self-serve: deactivate old → activate new. No ticket. |
| 10 | **Billing** | invoices | Download invoices/receipts; tax info if business. |
| 11 | **Support** | tickets/WA | From dashboard, with history. |
| 12 | **Cancel** | subscription | Auto-renew off; access until period end; clear messaging. |
| 13 | **Refund request** | admin approval | Request from dashboard → approval → **wallet credit** → notification. |

**Contact-type products:** step 2 → WA/Lead → admin quote → manual order/payment link → **same provisioning pipeline** → grant appears in the customer dashboard. (No second provisioning path.)

---

## B. Admin / Operator journey

1. **Login** (scoped permissions).
2. **Work queue** (unified): incoming Leads + support tickets + **failed renewals** + failed-provisioning. *(New requirement — not just Lead CRM.)*
3. **Lead → revenue:** Lead → quote/manual order → payment link or deduct balance → runs the **standard provisioner** → grant + invoice + notification.
4. **Support via Customer 360:** one screen (orders, balance, licenses, devices, tickets, timeline) → actions: resend key, resend invoice, extend, **transfer license**, reset seat/device, manual top-up/adjustment (reason required + audited).
5. **Product/release mgmt:** upload version/installer + changelog → notify owners.

**Connectivity rule:** every Admin action produces a downstream effect + notification + AuditLog entry.

---

## C. Superadmin journey

1. **First-run setup checklist** (defines the "A"): Duitku credentials → WA gateway → global settings (token TTL, grace days, min top-up, bonus rules) → tax/invoice identity → create StorePage → first product → invite Admins (RBAC). *(New requirement.)*
2. **Daily cockpit:** KPIs (balance float/liability, revenue recognized, active licenses, failed renewals, top-ups, orders, leads).
3. **Money oversight:** reconciliation (Duitku settlement ↔ ledger), liability vs revenue.
4. **Escalations:** approve refunds/large adjustments, abuse → revoke, **panic controls** (global grace extend / activation maintenance) so an API outage never bricks customers.
5. **System Health:** failed webhooks/jobs queue → retry (this is the safety net behind Customer step 4).
6. **People & governance:** manage admins/permissions, audit log.
7. **Growth:** vouchers, broadcast, analytics.

---

## D. Connectivity matrix (action → effect → notify → audit)

| Trigger | Downstream | Notify | Audit |
|---------|-----------|--------|-------|
| Top-up paid | balance +ledger | WA+email | — |
| Checkout | balance −ledger, grant issued | WA+email (key) | — |
| Renewal success | period extended, balance −ledger | WA | — |
| Renewal short | grace → suspend → product locks | WA+email (with top-up link) | — |
| Top-up after suspend | reactivate grant | WA | — |
| Refund approved | balance +ledger | WA+email | ✓ |
| Revoke (abuse) | license revoked → product locks | email | ✓ |
| Manual top-up/adjust | balance ±ledger | WA | ✓ |
| Webhook failed | System Health queue → retry | — (internal) | ✓ |

---

## E. Critical safety nets
- **Webhook failure** → pending state + auto-retry + reconciliation (protects Customer step 4).
- **Renewal** → forecast + reminders + grace + one-tap top-up (protects Customer step 8).
- **Seat full** → self-serve device management (protects Customer step 9).
- **API outage** → Superadmin panic controls / global grace (protects all active installations).

## F. Decided
- **Refund target:** **wallet credit only** (no refund to original payment source). Consistent with the closed-loop balance model.
- **First-purchase top-up amount:** **suggested packages + a pay-exact option** (e.g. exact-for-order / +50k / +100k).
- **Anonymous browsing:** **allowed**; login required only at checkout/top-up.
