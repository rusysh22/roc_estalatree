# 17 — Product Packaging & Catalog Design

> How offerings are structured commercially. Core stays small (Product + Plan + Deliverable + Entitlement); Add-ons and Bundles are compositions added in the growth stage.

## 17.1 Core building blocks

| Concept | Role |
|---------|------|
| **Product** | The thing (an OSS app, a managed service). Has metadata, visibility, media. |
| **Plan** | A *purchasable option* of a Product: pricing model (`free / one_time / recurring / contact`), price, interval, `seat_limit`, **Deliverables**, **Entitlements**. |
| **Deliverable** | What gets provisioned ([15](15-provisioning-and-entitlements.md)). |
| **Entitlement** | What features unlock ([15](15-provisioning-and-entitlements.md)). |

A Product with three Plans (Free / Pro monthly / Pro yearly) = classic good-better-best, differentiated purely by **Entitlements + seat_limit**, not duplicated code.

## 17.2 Compositions (growth stage)

- **Add-on** — optional extra attached to a Subscription (e.g. `+5 seats`, `priority support`). Modeled as a Plan flagged `is_addon`, billed from balance alongside the base plan.
- **Bundle** — one Plan that provisions Deliverables from **multiple Products** at a combined price.
- **Coupon / Voucher** — checkout-time discount (percentage/fixed/first-period). Part of the promo engine (Superadmin).
- **Top-up bonus tiers** — promo on the wallet side, not the catalog (e.g. top up 100k → +10k).

## 17.3 Pricing models recap

| Plan type | Billing | Lifecycle |
|-----------|---------|-----------|
| `free` | none | grant issued instantly |
| `one_time` | deduct balance once | permanent grant (lifetime) |
| `recurring` | deduct balance each interval (auto) | subscription, renew/grace/suspend |
| `contact` | manual quote → operator order | grant via `manual` provisioner |

## 17.4 Catalog presentation

- Storefront groups by Product; Plans shown as a comparison (features = Entitlements).
- `visibility`: `draft / unlisted / public`.
- Each Plan clearly states: price, interval, seat_limit, what's delivered, what features are included.

## 17.5 Design guidance

- **Keep Entitlements the source of truth for features** — never branch on plan name in code.
- **One Product, many Plans** beats many near-duplicate Products.
- Introduce Add-ons/Bundles only when a real offer needs them (avoid premature complexity).
