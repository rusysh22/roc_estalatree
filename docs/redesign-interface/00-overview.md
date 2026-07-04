# Public Interface Redesign — Overview

## Why

Berlanggan's public-facing surfaces (storefront, product pages, checkout, and everything a buyer or visitor touches without logging into the seller/admin tools) were built as a **single-merchant "link-in-bio" MVP**. The backend has since grown genuinely multi-seller-capable (`SellerProfile`, per-slug store pages, seller-scoped products), but the public UI never caught up: there is no marketplace discovery experience, no distinct brand identity, generic Tailwind indigo colors, and no interaction personality. It reads as an unfinished template, not a product with an identity.

This redesign rebuilds the public experience end-to-end, conceptually inspired by Gumroad and Lynk.id (multi-seller, link-in-bio-friendly, buyer-convenience-first) but with **Berlanggan's own visual identity** — not a copy of either.

## Goals

1. A real marketplace landing page at `/` — today root `/` just shows whichever seller's store page happened to publish first. Multi-seller platforms need an actual discovery homepage.
2. A distinct brand identity: unique color palette, friendly rounded/organic shapes, a confident single-family typeface system, and non-generic interactive animation — deliberately avoiding the generic "AI-generated SaaS template" look (default indigo/purple gradients, static fade-ins, stock icon grids).
3. Every public page redesigned with the buyer's point of view first: what's fastest to find, understand, and pay for.
4. Mobile-responsive at every step, not retrofitted at the end.

## Sequencing

Work proceeds **phase by phase**, each phase fully shipped (top of page to bottom, including mobile) before the next starts:

| Phase | Scope | Status |
|---|---|---|
| 1 | Marketplace landing page (`/`) — full header-to-footer redesign | Shipped — see [02-phase-1-landing-page.md](02-phase-1-landing-page.md) |
| 2 | Individual seller storefront page (`/<slug>/`) + product detail page (`/p/<slug>/`) | Shipped — see [04-phase-2-storefront-product.md](04-phase-2-storefront-product.md) |
| 3 | Checkout, order status, top-up flows | Shipped — see [05-phase-3-checkout-topup-orders.md](05-phase-3-checkout-topup-orders.md) |
| 4 | Auth pages (login/signup), legal pages, contact/lead form | Shipped — see [06-phase-4-auth-legal-contact.md](06-phase-4-auth-legal-contact.md) |
| 5 | Buyer dashboard (`/dashboard/`) — full visual pass | Shipped — see [07-phase-5-buyer-dashboard.md](07-phase-5-buyer-dashboard.md) |

Seller-facing console/dashboard tooling (`/seller/`, `/console/`) is **out of scope** for this redesign — it's an internal operator tool, not part of the public identity surface, unless explicitly requested later.

## Shared references

- Design system (colors, type, shape, motion rules): [01-design-system.md](01-design-system.md)
- Phase 1 detailed spec: [02-phase-1-landing-page.md](02-phase-1-landing-page.md)
- Future phase notes: [03-roadmap-future-phases.md](03-roadmap-future-phases.md)

## Working agreement

Requirements and design decisions are written down here **before** implementation for each phase. Code changes should trace back to a decision recorded in this folder — if an implementation detail isn't here yet, it isn't approved yet.
