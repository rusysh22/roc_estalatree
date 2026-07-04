# Production feedback — 2026-07-05

Source: live testing on berlanggan.web.id by the founder, after a real RoC Support Desk /
Professional purchase (guest checkout → Duitku → license issued). Raw feedback is preserved
per-point below; each point has root-cause research (with file:line references, verified
against the current codebase) and a proposed fix.

Grouped by feature area, roughly in priority order (live bugs first, then UX polish, then
new features).

**Status (2026-07-05):** Sections A–G implemented, tested (170 passing tests, 1 pre-existing
unrelated failure untouched), and verified visually via headless-browser screenshots.
Section H (cart) is intentionally NOT started — see the note at the end of that section;
it's a distinct architectural piece (multi-seller split payment) that deserves its own
dedicated pass rather than being folded into this batch.

---

## A. Guest order access is broken (P0 — live bug, affects every guest buyer)

**Reported (#1):** Clicking "View order details" in the confirmation email
(`https://berlanggan.web.id/orders/ord_0epb70cta8i0jao4/`) returns a plain Django 404 "Not
Found."

**Root cause.** `order_status` (`apps/storefront/views.py:512-523`) is `@login_required` and
then does `get_object_or_404(Order..., public_id=public_id, customer=customer)` where
`customer` comes from whoever is *currently logged in*. A flat 404 (not a redirect to
login) only happens when the visitor **is** authenticated but as the wrong account — i.e.
`Order.customer_id` doesn't match their current session's customer.

This is a structural gap, not a one-off glitch: guest checkout (`apps/storefront/views.py:295-301`)
creates the account with `user.set_unusable_password()`. That account can never log back in
with a password, and there is no passwordless/magic-link re-entry path today. So the moment
a guest's session is lost (closes the tab, opens the email later on another device, clears
cookies, or later signs in some other way that resolves to a different account), they have
**no way back into the exact account that made the purchase** — clicking the email link either
bounces them to a login form they can't complete, or — if they happen to be logged into some
other account — silently 404s like this.

**Proposed fix — signed, login-independent order links.**
Stop relying on session auth for the confirmation-email link. Sign the order URL with
Django's `django.core.signing` (same trust model as the allauth confirmation link already
uses), e.g. `storefront:order_receipt` at `/orders/<public_id>/receipt/?token=...`, valid
indefinitely (or long-lived, e.g. 90 days) and re-derivable by re-sending the confirmation
email or a "resend receipt" action. This sidesteps the whole "which account are you logged in
as" problem for the one link that most needs to always work.

Secondary/complementary fix — give guest accounts a real way back in:
- Add "Forgot password" as a first-class link on the login page for guest accounts (it
  already technically works via allauth's reset flow even with `set_unusable_password()`,
  since reset issues a *new* password rather than checking the old one — but this isn't
  surfaced anywhere as "how do I get back into my guest account").
- Longer-term: passwordless/magic-link login for accounts with no usable password, so
  "log back in" is a one-click email link rather than a password-reset detour.

**Affected files:** `apps/storefront/views.py` (new `order_receipt` view alongside
`order_status`), `apps/storefront/urls.py`, `apps/notifications/tasks.py`
(`deliver_order_confirmation_email` — point the CTA at the signed URL instead of
`order_status`), `templates/emails/order_confirmation.html`.

**Decided:** long-lived (no expiry / effectively permanent — treat it like a paid invoice PDF
link, not a security-sensitive action).

---

## B. Order confirmation email — content & design gaps

**Reported (#2):**
1. "Design kurang lengkap" — wants order date/time, buyer info, and other receipt details;
   wants a PDF invoice attached showing the bill is paid, plus the access
   credentials in the same email.
2. Logo doesn't show up in the email (screenshot shows broken image + wrapping alt text
   "Berl angga").
3. "If possible" — copy-to-clipboard button on the credentials block (explicitly said: skip
   it if not feasible).

**Root cause — missing logo.** The email's `<img src="{{ site_url }}{% static
'images/brand/logo-mark.png' %}">` (`templates/emails/base.html:17`) depends on
`STATIC_URL`/`STATICFILES_STORAGE` resolving to a URL that's actually reachable from the
recipient's mail client over the public internet. Two likely causes, need to confirm on the
VPS:
- `{% static %}` may be resolving to a path that isn't being served correctly by nginx's
  `location /static/ { alias /app/staticfiles/; }` (`nginx/conf.d/app.conf:34-36`) if
  `collectstatic` didn't pick up `static/images/brand/logo-mark.png` into
  `/app/staticfiles/images/brand/logo-mark.png` on the last deploy.
- Some email clients (Outlook, some corporate scanners) block/strip external images by
  default until the user clicks "show images" — the broken-alt-text wrapping in the
  screenshot ("Berl / angga") looks exactly like a client rendering fallback `alt` text at
  the `<img>`'s fixed 48×48 box, which is more consistent with **image blocked by client**
  than a broken URL. Needs a real inbox test (not just curl) to tell these apart.
- Fix regardless of cause: verify `https://berlanggan.web.id/static/images/brand/logo-mark.png`
  loads in a browser after the next deploy; if it 404s, `collectstatic` needs a forced re-run
  (`docker compose exec web python manage.py collectstatic --noinput`) or a volume issue on
  `static_data` needs investigating. Also add explicit `width`/`height` and `alt="Berlanggan"`
  (already present) so the fallback at least reads as one word, and consider inlining the
  logo as a small base64 `data:` URI for the email specifically (fully client-independent,
  common practice for transactional email logos) as a robustness upgrade.

**Design/content additions (all straightforward template additions to
`templates/emails/order_confirmation.html`):**
- Order date/time (`order.created_at`), buyer name/email if available (`order.customer.user`).
- A line-item style breakdown (plan name, base price, discount if coupon used, final total) —
  currently only shows the final `order.amount`.
- Restate the credentials/access block more prominently as "Sudah Lunas" / "Paid in full"
  status badge.

**PDF invoice attachment — new capability.** No PDF generation exists anywhere in the repo
today. Needs a new dependency (e.g. `weasyprint` or `reportlab`) plus an invoice HTML→PDF
template, generated in `deliver_order_confirmation_email`
(`apps/notifications/tasks.py:78-111`) and attached via `msg.attach(filename, pdf_bytes,
"application/pdf")`. `Order.invoice_number` already exists
(`apps/billing/checkout.py:74-81`, assigned sequentially) so there's already a stable invoice
numbering scheme to build the PDF around — this is additive, not a redesign.

**Copy-to-clipboard button — feasible, in-scope.** Plain email HTML/CSS cannot run
JavaScript (all major email clients strip `<script>`), so a "Copy" *button* inside the email
itself is not achievable — this part of the ask isn't possible for the reason you already
allowed for ("jika tidak bisa tidak usah diimplementasi"). What **is** achievable: make the
license key text itself trivially select-all-and-copy-friendly (already the case — it's
plain text in a `<td>`), and add copy-to-clipboard on the **web version** (the linked order
receipt page from section A), which already has JS available. Recommend implementing copy
there instead, since that's the one place it can actually work.

**Reported (#3):** Top-up confirmation email should also show more detail.
`templates/emails/topup_confirmation.html` currently shows amount + bonus only. Add: date/time,
resulting wallet balance after credit (needs passing `wallet.balance` into
`deliver_topup_confirmation_email`, `apps/notifications/tasks.py:121-148`), and the
top-up's `public_id` as a reference number.

---

## C. Checkout/top-up page UX polish

**Reported (#5):** Amount fields should use standard Indonesian thousands separators (dot)
— e.g. `Rp1.884.600` not `Rp1884600`.

Good news: `apps/core/formatting.py`'s `format_rupiah()` (used via the `rupiah` template
filter, `apps/core/templatetags/money.py:57-59`) already does this correctly — the order
confirmation email screenshot itself shows `Rp1.884.600` formatted correctly. This request is
most likely about a **specific input field** that doesn't use the filter — almost certainly
the raw `<input type="number">` amount field on the top-up page
(`apps/storefront/templates/storefront/topup.html:39-41`), which necessarily shows a raw
unformatted number while being typed/edited (HTML number inputs can't display separators).
Fix: add a live-formatting JS behavor (format on blur / display a formatted "preview" beside
the input, matching common Indonesian fintech UX), not a backend change. Needs a short
`site.js` addition (`initAmountFormatting()` in the same style as the existing `initXxx()`
helpers) — format-with-dots-as-you-type on the amount `<input>` while keeping the underlying
submitted value numeric.

**Reported (#6):** The top-up "quick amount" chips (50,000 / 100,000 / 200,000 / etc. —
`topup.html`) should visibly highlight which one is currently selected.

Straightforward: these are currently plain buttons that populate the amount field on click
with no persisted "active" state. Add a `data-amount-chip` attribute + a small `site.js`
handler that toggles an `is-selected` class (coral border/background, matching the existing
`has-[:checked]` treatment already used for payment method radios in
`_payment_method_picker.html:16-17`) and clears it if the user then hand-edits the amount
field to a non-matching value.

**Reported (#7):** Payment methods within a group should be ordered by real-world popularity
(VA: BCA, BNI, BRI, ... ; QRIS: ShopeePay QRIS, LinkAja QRIS, NOBU QRIS, ...) instead of
whatever order Duitku's API returns.

Confirmed via code read: `get_payment_methods()` (`apps/billing/duitku.py:159-189`) and
`_group_payment_methods()` (`apps/storefront/views.py:71-80`) preserve Duitku's raw API
order with **no** intra-group sorting today — `PAYMENT_METHOD_GROUPS`
(`apps/storefront/views.py:61-68`) only orders the *groups themselves* (VA → QRIS → E-Wallet
→ Retail → Card → Other), not the methods inside each group.

Fix: add a priority list keyed by Duitku's payment method `code` (need the actual codes from
a live `get_payment_methods()` response — e.g. Duitku's BCA VA code, BNI VA code, etc. — to
map correctly; codes weren't visible in this session's investigation and should be pulled
from a sandbox/live API call before implementing), then sort each group's methods by
`priority_list.index(code)` (unlisted codes sink to the end, keeping current relative order
as a stable fallback). Small, self-contained change in `_group_payment_methods()`.

**My addition:** this priority list will need periodic manual tuning as customer payment
habits shift — worth a one-line comment pointing at wherever `PAYMENT_METHOD_GROUPS`-adjacent
priority list lives so it's easy to find and update later, rather than burying it deep in
`duitku.py`.

---

## D. Product packaging — multi-duration options

**Reported (#8):** The product page shouldn't only offer the "Professional" plan — should
also offer 1/3/6-month (etc.) packages.

Research clarified this is **not** about missing pricing tiers — RoC Support Desk already
has 4 separate `Plan` rows seeded (Starter/Professional/Business/Enterprise,
`apps/catalog/management/commands/seed_roc_support_desk.py`, `PLAN_SPECS` lines 42-47), and
the buyer specifically chose "Professional." The actual gap: **duration packaging within a
plan**. The codebase already has this mechanism built and working —
`Plan.duration_discounts` (JSONField, `apps/catalog/models.py:72-75`) plus a duration-multiplier
selector already rendered in checkout when populated
(`apps/storefront/templates/storefront/checkout.html:29-90`, gated on
`plan.interval != 'none' and plan.duration_discounts`) — but the seed command never
populates `duration_discounts` for any of the 4 RoC Support Desk plans (defaults to `{}`), so
the selector never appears for this product today.

**Proposed fix:** this is a **content/data fix, not a code fix** — populate
`duration_discounts` on the RoC Support Desk plans (e.g. `{"3": 5, "6": 10, "12": 15}` per
the existing convention seen elsewhere) via the seed command or directly through the seller
dashboard's plan editor (`PlanForm` already exposes `duration_discounts`,
`apps/seller/forms.py:48-62`). Secondary UX improvement worth doing alongside: the duration
selector is currently tucked inside the checkout page rather than visible on the product page
itself — consider surfacing "from Rp X/mo (up to N% off on longer plans)" on the product
listing card so buyers see the packaging options before they even click into checkout.

---

## E. Branding consistency

**Reported (#9):** `/seller/apply/` doesn't use the site logo.

Confirmed: `apps/seller/templates/seller/apply.html:8-10` renders a placeholder colored div
with a hardcoded letter "E" instead of `{% static 'images/brand/logo-mark.png' %}` (used
correctly everywhere else — nav, footer, console, dashboard, emails). Simple, isolated fix —
swap the placeholder for the real logo `<img>`, matching the pattern already used in
`apps/dashboard/templates/dashboard/base.html:30`. Worth a quick sweep for any other
leftover "E" placeholder marks from the pre-rebrand era while in this file.

---

## F. Seller onboarding — guided store setup (new feature)

**Reported (#10):** Build a guided form flow for first-time store setup — some fields
required, some skippable, so a new seller knows what to fill in.

Research shows today's flow is a **flat, single-step edit form** with almost nothing
enforced: `store` view (`apps/seller/views.py:499-539`) gets-or-creates one `StorePage` and
renders `StorePageForm` (title/description/avatar_url — only `title` is actually required at
the model level) alongside a theme form. A seller must separately, manually:
`store_publish_toggle` to go live (`apps/seller/views.py:542-554`) and `block_add` to attach
each product to the page (`apps/seller/views.py:557-577`) — none of this is
sequenced or explained today.

**Decided: the wizard itself is mandatory** — a first-time seller cannot reach the regular
seller dashboard until they've been through it (no "skip for now, I'll finish later on the
dashboard" escape hatch). Individual steps/fields inside it keep the required-vs-skippable
mix from the original ask:

1. **Store identity** (required): store name (already collected at apply-time), avatar/logo
   upload (skippable — falls back to the default mark), short description/bio (skippable).
2. **First product** (required to advance — a store with zero products has nothing to sell):
   product name, type, one plan with a price. Skippable *within* the step only in the sense
   that optional product fields (description, cover image, WA number) can be left blank.
3. **Store page layout** (auto-handled, not a real gate): the product from step 2 is
   auto-attached as a block; reordering/adding more blocks is optional and always editable
   later from the normal dashboard — no need to force this inside the wizard.
4. **Publish** (required to exit the wizard): explicit "Go live" action = the existing
   `store_publish_toggle`. Since the wizard is mandatory, "save as draft and come back later"
   is not an option here — finishing the wizard means the store is live.

Implementation shape: a `SellerProfile.onboarding_step` field to track progress and enforce
the gate, a middleware/decorator check (alongside `seller_required` in
`apps/seller/decorators.py`) that redirects any seller with an incomplete wizard to
`seller/onboarding/` regardless of which seller URL they try to hit, and a dedicated
`seller/onboarding/` view+template set reusing existing forms (`StorePageForm`, `ProductForm`,
`PlanForm`) sequenced with progress UI.

---

## G. Remove seller approval review step

**Reported (#11):** No review needed to create a store or apply as seller — just require a
logged-in, email-verified user.

Research shows `is_approved` already defaults to `True` at the model level
(`apps/accounts/models.py:89`, `models.BooleanField(default=True)`), but the **apply view
explicitly overrides it to `False`** on every new application
(`apps/seller/views.py:831`), and nothing anywhere in the codebase ever flips it back to
`True` except manual Django-admin editing — so today, every applicant is *stuck* pending
forever unless an operator manually toggles the field in `/admin/`. This reads as an
intentional-but-unfinished manual-review gate — the review "step" was likely meant to be a
console approval action that never got built (this session's earlier exploration confirmed
`apps/console/` has customer/audit views but no seller-approval UI or action).

**Proposed fix:**
1. Change `apps/seller/views.py:831` to set `is_approved=True` immediately on apply,
   conditioned on the applicant's primary email being verified
   (`allauth.account.models.EmailAddress.objects.filter(user=user, verified=True).exists()`)
   — if not verified, redirect to the email-verification step first with a clear message,
   rather than creating a permanently-pending `SellerProfile`.
2. Remove/repurpose the "Application Pending" UI block in `apply.html:15-20` — with
   instant approval it should only ever show transiently if verification is still pending,
   not as a permanent dead-end state.
3. **Decided:** keep `is_approved` as a field for future moderation/suspension use (e.g.
   banning a seller), just remove it from the *application* critical path entirely.

**Ties into item A/section G:** this is exactly why enforcing email verification matters —
once approval is automatic, verified-email is the only remaining gate against
fake/abusive seller signups, so section A's guest-verification work and this item should land
together.

---

## H. Shopping cart (new feature)

**Reported (#12):** Build a cart page so buyers can accumulate items before checkout/payment.

Confirmed there is no cart concept anywhere today — checkout is single-plan,
direct-from-product-page (`apps/storefront/urls.py:11`,
`storefront/templates/storefront/product.html:165` links straight to
`storefront:checkout` with one `plan_pk`). This is the largest item in this feedback batch —
a genuinely new subsystem, not a fix to existing code. Sketching the shape rather than fully
speccing it here (deserves its own planning pass once you confirm you want it prioritized):

- New `Cart`/`CartItem` models (session-bound for guests, user-bound once logged in — needs a
  merge strategy for "add to cart as guest, then log in").
- **Decided: carts can span multiple sellers.** This means checkout/payment must **split into
  one `Order` + one Duitku invoice per seller** at pay time — Duitku (like virtually every
  Indonesian payment gateway) settles to a single merchant account per invoice, so there is no
  way to pay multiple sellers in a single gateway transaction. Concretely:
  - One `Cart` can hold `CartItem`s from many sellers.
  - At "pay now," group `CartItem`s by `plan.product.seller`, create one pending `Order` per
    seller group (reusing `checkout()`'s per-plan logic, `apps/billing/checkout.py`, looped
    per seller), and either (a) if the whole multi-seller total needs a gateway payment, create
    **one Duitku invoice per seller-group** and walk the buyer through them sequentially
    (pay seller A's invoice → redirect back → pay seller B's invoice → ...), or (b) if wallet
    balance alone covers everything, debit once per seller-group order in a single atomic
    transaction with no gateway involvement at all.
  - Sequential multi-invoice payment is a real UX cost worth flagging now: the buyer sees
    "2 of 3 payments complete" style stepping rather than one checkout. This is inherent to
    splitting settlement across sellers with today's payment gateway — not something to design
    around, just something to design *for* (clear progress UI, ability to abandon after
    partial payment without losing what's already been paid for).
  - `TopUp.checkout_order` is currently a `OneToOneField` (`apps/billing/models.py:40`) —
    tying one TopUp to one Order. A multi-seller cart checkout that needs top-up-and-buy for
    more than one seller-group in the same pass will need this relationship reworked (e.g. a
    `OneToMany` or a separate `CartCheckoutSession` grouping multiple Orders under one
    top-up), since one wallet top-up could legitimately need to fund several simultaneous
    per-seller orders.
- Coupon/discount interaction: today coupons apply per-plan at checkout
  (`apps/billing/checkout.py:281-286`) — with multi-seller carts, the natural rule is a coupon
  applies per cart-line (i.e. per plan), same as today, rather than spanning the whole cart —
  avoids ambiguity about which seller "absorbs" a cart-wide discount.
- Duration-multiplier and PWYW pricing (sections C/D) both currently live on the
  single-plan checkout page and would need to move into a per-line cart-item config UI.

**Recommend treating this as Phase 2** of this feedback round (after A–G, which are mostly
bug fixes and small additive UX) given its size — the multi-seller split-payment flow above is
a substantial new piece of billing logic and deserves its own focused implementation pass
rather than being folded into the smaller fixes.

---

## Suggested implementation order

1. **A** (guest order-link 404) — live bug affecting every guest buyer today, highest priority.
2. **E** (apply page logo) — 5-minute fix, do alongside A.
3. **G** (remove approval gate) + **F** (onboarding wizard skip logic ties in) — unblocks
   real sellers from getting stuck in "pending" limbo.
4. **B** (email logo/content/PDF invoice) — logo fix is urgent (every email since deploy has
   been sending a broken image); content/PDF additions can follow.
5. **C** (amount formatting, chip highlight, payment method ordering) — small, independent,
   can be done in any order/parallel.
6. **D** (duration_discounts data fix for RoC Support Desk) — pure data change, near-zero risk.
7. **F** (full onboarding wizard) — bigger UI feature, do once G unblocks real sellers.
8. **H** (cart) — largest scope, needs a product decision on multi-seller carts before
   design starts; treat as its own phase.

## Decisions (confirmed 2026-07-05)

- **A:** signed order-link — long-lived, no expiry.
- **F:** the onboarding wizard is mandatory — no "skip for now" escape to the dashboard.
- **G:** keep `is_approved` as a field for future moderation/ban use, just remove it from the
  apply critical path.
- **H:** carts can span multiple sellers — checkout splits into one Order + one Duitku
  invoice per seller-group at pay time (see section H for the sequential-payment design
  implication).
