# 04 — Products & Pricing

> See also [17-product-packaging.md](17-product-packaging.md) for the full packaging model (plans, add-ons, bundles, entitlements).

## Product Types

Each product has one pricing type:

| Type | Behavior |
|------|----------|
| **Free** | License issued instantly, no payment. |
| **One-time** | Deduct balance → permanent (lifetime) license. |
| **Recurring** | Deduct balance → license active for the period; auto-deduct each cycle. |
| **Contact (WA)** | No checkout; the button opens WhatsApp → captured as a **Lead**. |

## Plan / Variant

- A product has one or more **Plans**.
- A Plan defines: `price`, `interval` (for recurring: monthly/yearly), `seat_limit` (number of installations), `features`.
- Example: Product "X" has a **Monthly (1 seat)** plan and a **Yearly (3 seats)** plan.

## Digital Delivery

A product can deliver one or more of:
- **License Key** (for OSS products requiring token activation).
- **File download** (installer / asset).
- **Access link** (web app / private repo).
- **Private release installer**.

> Delivery is generalized via the provisioning model — see [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md).

## Visibility

- `draft` — not shown.
- `unlisted` — accessible by link, hidden from the catalog.
- `public` — shown in the storefront.

## Notes

- The **Contact** type is often used for enterprise/custom products; an Admin converts the lead into a **manual invoice/order** (see [09-features.md](09-features.md)).
- The **Free** type still issues a license and can use token activation (useful for freemium / limiting installations).
