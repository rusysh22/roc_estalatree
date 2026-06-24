# UI & Menu Enhancement Spec (Update 2026-06-19)

**Author:** assistant (review-only). **Audience:** implementing AI agent.
**Purpose:** precise, implementation-ready brief for: (0) rupiah formatting system-wide, (0b) a render bug, (1) completeness verdict, (2) per-menu enhancements (UI + backend). Each task has **Acceptance Criteria (AC)**. Follow [CONVENTIONS.md](../CONVENTIONS.md) (no emoji icons; English; money helpers).

---

## 0. Rupiah thousands separator — system-wide (HIGH, do first)

### Problem
Templates render money as `Rp{{ amount|floatformat:0 }}`. `floatformat:0` rounds but adds **no** thousands separator, producing `Rp1000`, `Rp-99000`, `+Rp100000`. No shared money filter exists. Indonesian format must be **dot-grouped, no decimals**: `Rp1.000`, `-Rp99.000`, `+Rp100.000`.

### Solution — one shared helper + two template filters
Create **`apps/core/formatting.py`**:
```python
def format_rupiah(value, *, signed: bool = False) -> str:
    v = int(value or 0)
    grouped = f"{abs(v):,}".replace(",", ".")        # 99000 -> "99.000"
    sign = "-" if v < 0 else ("+" if signed and v > 0 else "")
    return f"{sign}Rp{grouped}"
```
Create **`apps/core/templatetags/money.py`**:
```python
from django import template
from apps.core.formatting import format_rupiah
register = template.Library()

@register.filter
def rupiah(value): return format_rupiah(value)

@register.filter
def rupiah_signed(value): return format_rupiah(value, signed=True)
```
Add `apps.core` templatetags are auto-discovered; in each template `{% load money %}`.

### Apply everywhere (replace pattern)
- Replace `Rp{{ X|floatformat:0 }}` → `{{ X|rupiah }}` in **all** templates under:
  `apps/dashboard/templates/`, `apps/storefront/templates/`, `apps/seller/templates/`, `apps/console/templates/`.
- Ledger amount cell (`partials/ledger_rows.html`): use the signed variant and drop the manual `+`:
  `{{ entry.amount|rupiah_signed }}` (yields `+Rp100.000` / `-Rp99.000`). Keep the green/red class logic.
- **Non-template money strings** must use `format_rupiah` too (currently `f"Rp{x:,}"` = comma):
  `apps/notifications/handlers.py`, `apps/notifications/reminders.py`, `apps/billing/*` notes.
- Optional but recommended for consistency: model `__str__` in `wallet/models.py`, `billing/models.py` → `format_rupiah(...)`.

### AC
- `1000 → Rp1.000`, `-99000 → -Rp99.000`, `+100000 (signed) → +Rp100.000`.
- No occurrence of `floatformat:0` remains for money. No comma-grouped rupiah anywhere (templates, WA/email, admin __str__).

---

## 0b. Bug — ledger TYPE column renders blank
`partials/ledger_rows.html` calls `entry.get_entry_type_display`. The model field is `type` → the accessor is **`get_type_display`**. The wrong name silently resolves to empty (Django templates swallow it), so the TYPE chip shows color only, no label.
- **Fix:** `{{ entry.get_type_display }}`.
- **AC:** TYPE column shows "Top-up", "Purchase", etc.

---

## 1. Completeness verdict (honest)

| Area | State | Main gaps |
|------|-------|-----------|
| **Subscriptions (backend)** | ~95% | Solid: renew/grace/suspend/reactivate, cascade, idempotent. Minor: cancel→cancelled UX. |
| **Customer dashboard** | ~85% | No PDF invoices; no notification preferences; no support tickets; no 2FA/social-mgmt; credentials/api_key grants have no shown-once reveal. |
| **Console** | ~85% | Refund doesn't set `Order.REFUNDED` → revenue KPI gross (verify/close); work-queue links point to `/admin/` (operators); no reconciliation/abuse views; H2a (`is_staff` gating) residual. |

Not "perfect" — but no architectural rework needed; gaps are feature-completion + polish.

---

## 2. Per-menu enhancements (UI + Backend)

### 2.1 Wallet
**UI**
- Apply `rupiah` (§0) + fix TYPE label (§0b).
- Show **pending top-ups** with a "Check status" action (calls a recheck endpoint) — journey step 4 safety net is invisible today.
- "Low balance" badge when `balance < cheapest active plan` / next renewal shortfall.
- Quick top-up chips (50k/100k/200k…) on the wallet page itself.
**Backend**
- Enforce `MIN_TOPUP`/`MAX_TOPUP` (Setting) in `storefront.topup` (open item M2).
- Expose a `topup_status` view that calls `recheck_topup_status` for the customer's pending top-ups.
**AC:** amounts formatted; pending top-ups visible + refreshable; below-min top-up rejected.

### 2.2 Products (My Products)
**UI**
- **Copy-to-clipboard** for license keys (no emoji; use a Heroicon SVG button).
- Per-deliverable rendering by `grant.type`: `license_key`→key+activation guide; `download`→download button; `access_link`→open link; `credentials`/`api_key`→**reveal-once** then masked.
- Seat usage `active_seat_count/seat_limit` with a "manage devices" link.
**Backend**
- **Secret reveal endpoint** for `credentials`/`api_key`: read from the encrypted `Secret` model (see Final-Review H1 — secrets must move out of `Grant.payload`), set `Secret.is_revealed=True`, audit. Mask after first reveal.
- Activation guide text from `deliverable.config` or a product field.
**AC:** key copyable; secret shown once then masked; download/link/credential render correctly per type.

### 2.3 Subscriptions
**UI**
- Status badge (active/grace/suspended/cancelled); **next charge** amount + date; shortfall warning + Top-up CTA; **grace countdown** banner.
- Auto-renew toggle already present — add a confirmation + "what happens" helper text.
**Backend**
- Forecast: reuse `_renewal_forecast`. Ensure SUSPENDED subs show a "Top up to reactivate" CTA (Phase 6 M1 path).
**AC:** customer can always see next charge, shortfall, and how to stay active; toggling auto-renew is clear.

### 2.4 Invoices
**UI**
- Unified, paginated list (orders + top-ups), status, formatted amounts; per-row "Download PDF".
- Invoice detail page showing merchant identity (`INVOICE_NAME`, `TAX_ID`) and PPN line if enabled.
**Backend**
- **PDF generation** (WeasyPrint or ReportLab) — currently only a list; the spec promised invoice PDFs.
- Sequential invoice number (immutable) separate from `public_id`.
- Decide PPN: if enabled, compute & show tax line (open question).
**AC:** every PAID order/top-up has a downloadable PDF with merchant + (optional) tax info and a stable invoice number.

### 2.5 Profile
**UI**
- Links to allauth: **change password**, **manage Google connection**, **email + verification status**.
- **Notification preferences** (WA on/off, email on/off) — currently notifications send unconditionally.
- (Stage 2) 2FA enrollment via allauth MFA.
**Backend**
- `NotificationPreference` (or fields on Customer); have Phase-7 handlers respect it before dispatch.
- Wire email-verification decision (currently `ACCOUNT_EMAIL_VERIFICATION="optional"`) — if "required", gate purchase/top-up.
**AC:** customer can change password, see verification state, toggle channels; handlers honor preferences.

### 2.6 Support
**UI**
- Today it only shows a WA number. Add a **ticket form** + **ticket history** thread.
- FAQ/links section.
**Backend**
- `SupportTicket` + `SupportMessage` models (customer ↔ operator thread); surface open tickets in the **console work queue** (replaces the missing unified queue item) and Customer 360.
- Notify operator on new ticket; notify customer on reply (reuse Phase 7 channels + NotificationLog dedup).
**AC:** customer can open a ticket and see replies; operator sees it in the console queue; both sides notified.

---

## 3. Priority order
1. **§0 rupiah filter + §0b TYPE bug** (small, system-wide, visible). 
2. **§2.2 Products** secret-reveal + key copy (depends on Final-Review H1 secret move).
3. **§2.4 Invoices PDF** + **§2.1 Wallet** pending-topup/min-topup.
4. **§2.3 Subscriptions** forecast/grace polish.
5. **§2.5 Profile** notification prefs + email-verification decision.
6. **§2.6 Support** tickets (new models — larger).

Each item: implement → add/adjust tests → run the golden-path smoke test → check off here.
