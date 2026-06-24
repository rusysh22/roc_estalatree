# Selling Digital Files & Links (download / GDrive / URL) — Estalatree vs Lynk.id

**Date:** 2026-06-20 · **Reviewer:** assistant (review-only).
**Question:** can Estalatree sell a downloadable file or a GDrive/Dropbox/any-URL link "like lynk.id", and how does it compare in detail?

## Verdict
**Conceptually yes — operationally not yet.** Estalatree already models file/link selling (`Deliverable` types `download` + `access_link`, URL in config), but: (1) **two bugs make the link never reach the buyer**, (2) there is **no file hosting** (link-only), (3) the **store card has no image** and (4) the **purchase email omits the link**. Against lynk.id's polished, hosted, gated download flow, this is a ▲▲▲ gap today — but most of it is small fixes, not architecture.

---

## Bugs found (must-fix — file/link products are currently undeliverable)

### BUG-1 — payload key mismatch → buyer always sees "not available yet" (P1, blocking)
- `DownloadProvisioner` stores `payload={"download_url": ...}`; `AccessLinkProvisioner` stores `payload={"access_url": ...}`.
- `dashboard/products.html` reads `grant.payload.url` for both → the condition is always false → the buyer sees **"Download link not available yet." / "Access link not available yet."**
- **Fix:** align keys — store `"url"` in both provisioners, or read `payload.download_url`/`payload.access_url` in the template. (Pick one canonical key.)
- **AC:** a download/access purchase shows a working Download/Open button.

### BUG-2 — purchase email omits the download/access link (P1)
- `notifications/handlers.handle_order_paid` builds only `license_key` lines; for `download`/`access_link`/`credentials` grants nothing is included.
- The buyer gets a "purchase successful" email with **no link**.
- **Fix:** in the email/WA body, include per-grant delivery: download/access URL, or a deep link to the dashboard Products page.
- **AC:** buyer receives the access link (or a dashboard link) in the confirmation.

---

## End-to-end flow comparison

| Stage | Lynk.id | Estalatree (now) |
|-------|---------|------------------|
| **Seller: create product** | Title, **rich description**, **cover image + gallery**, price options (fixed / **pay-what-you-want** / free / min) | Product (name, text description, **no image**), Plan (fixed price / free), Deliverable `download`/`access_link` |
| **Seller: provide the file** | **Upload & host on platform** (size limits) **or** paste external link | **External URL only** (paste GDrive/Dropbox/any link) — no upload/hosting |
| **Storefront card** | Image-rich card (cover, price, CTA, sold-count, rating) | **Text-only card** (name, 2-line desc, price, Buy) — no image/social proof |
| **Checkout** | Direct pay, many methods, guest checkout | Login + wallet (top-up-and-buy); Duitku methods |
| **Delivery** | Instant gated download in library + **email with link** | Grant created — **but BUG-1 hides the link**, **BUG-2 email lacks it** |
| **Buyer access** | "My Purchase" library: re-download, receipt, magic link | Dashboard → My Products → (once BUG-1 fixed) Download/Open button; reveal-once for credentials |
| **Link protection** | Hosted file gated behind purchase/login; can limit downloads | **Static URL** stored; once shown it's the raw shareable link — no expiry, no per-buyer token, no download cap |

---

## Capability comparison (file/link selling specifically)

| Capability | Lynk.id | Estalatree | Gap |
|---|---|---|---|
| Native file upload + hosting | Yes | No (link-only) | ▲▲▲ |
| External link (GDrive/etc.) | Yes | Yes | — |
| Multiple files per product | Yes (file list) | Multiple deliverables possible, no file-list UX | ▲▲ |
| Product cover image / gallery | Yes | **No image field on Product** | ▲▲▲ |
| Pay-what-you-want / min price | Yes | No (fixed or free) | ▲▲ |
| Gated / expiring / per-buyer download | Yes | No (static shared URL) | ▲▲▲ |
| Download count / limit | Yes | No | ▲▲ |
| Email delivery of the link | Yes | **No (BUG-2)** | ▲▲▲ |
| Buyer library + re-access | Yes | Yes (dashboard), once BUG-1 fixed | ▲ |
| Stock / quantity limit | Yes | No | ▲ |
| Reviews / sold-count / rating | Yes | No | ▲▲ |
| Custom thank-you / delivery note | Yes | No | ▲ |

---

## Recommendations (to match lynk.id on file/link selling)

**P1 — make it actually work + presentable**
1. Fix **BUG-1** (payload key) and **BUG-2** (email includes link). Without these, file/link products don't deliver.
2. Add a **cover image** field to `Product` (+ optional gallery) and render it on the storefront card and product page. This is the single biggest presentation gap for digital-product selling.
3. Include **delivery instructions** field per deliverable (e.g., "extract with password X", "request access on the GDrive link").

**P2 — protection & pricing depth**
4. **Gated delivery**: instead of exposing the raw URL, serve a server-side redirect (`/download/<grant-token>/`) that checks the grant is active and (optionally) counts/limits/expires — turns a shareable link into a per-buyer gated download. For hosted files, use signed/expiring object-storage URLs.
5. **File hosting**: optional native upload to S3-compatible storage (then signed URLs) so sellers don't need GDrive.
6. **Pay-what-you-want / minimum price** option on Plan.
7. **Download count + expiry** on the grant.

**P3 — polish/parity**
8. Reviews/ratings + sold-count badges; stock/quantity limit; custom thank-you/delivery note; multiple-file list UX.

---

## Bottom line
Estalatree *can* sell GDrive-style file/link products today — the model is right — but it is **not delivering them** because of two small bugs, and it **looks plainer and protects the file less** than lynk.id (no image, no gating, link-only, no email link). Fix BUG-1/BUG-2 first (file/link selling is broken until then), add a product cover image, then layer gated delivery + PWYW to reach lynk.id's standard. None of this needs architectural change — the provisioning layer already supports it.
