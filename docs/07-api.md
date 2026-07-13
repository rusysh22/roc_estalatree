# 07 — Activation API (Django Ninja)

Base path: `/v1`. Format: JSON. Product auth: `license_key` + `secret` (header `X-Berlanggan-Secret`). Rate limited. Responses are signed.

> Internal endpoints (top-up, checkout, dashboard) use Django sessions/HTMX and are **not** documented here; this section covers only the API that OSS products call.

---

## `POST /v1/activate`
Register a new installation & issue a token.

**Request**
```json
{ "license_key": "XXXX-XXXX-XXXX", "fingerprint": "sha256...", "machine_name": "DESKTOP-01" }
```
**Response — success**
```json
{
  "status": "active", "token": "<signed>", "expires_at": "2026-07-01T00:00:00Z",
  "token_expires_at": "2026-07-01T00:00:00Z", "license_expires_at": "2027-06-01T00:00:00Z", "grace_days": 3,
  "entitlements": {"MAX_AGENTS": 10, "WHATSAPP": true},
  "entitlement": {"license_id": "...", "fingerprint": "...", "product_id": "...", "status": "active", "issued_at": "...", "license_expires_at": "...", "token_expires_at": "...", "entitlements": {}},
  "entitlement_signature": "base64-ed25519-signature"
}
```
**Response — failure**
```json
{ "status": "invalid|expired|seat_full|revoked|suspended", "message": "..." }
```

---

## `POST /v1/validate` (heartbeat)
Periodic status check; refresh the token while still active.

**Request**
```json
{ "license_key": "XXXX-XXXX-XXXX", "fingerprint": "sha256...", "token": "<signed>" }
```
**Response**
```json
{ "status": "active|grace|expired|revoked|suspended", "token": "<signed?>", "token_expires_at": "...", "license_expires_at": "...", "entitlement": {...}, "entitlement_signature": "..." }
```

---

## `POST /v1/deactivate`
Release an installation (free a `seat_limit` slot to move machines).

**Request**
```json
{ "license_key": "XXXX-XXXX-XXXX", "fingerprint": "sha256..." }
```
**Response**
```json
{ "status": "deactivated" }
```

---

## Rules
- Token short TTL (default 7 days, from `Setting`) + `grace_days`.
- `validate` returns a fresh token as expiry approaches (sliding) → the product always holds a fresh token while the subscription is active.
- All activation attempts and important errors are logged (for abuse monitoring).
- Idempotent: `activate` with an already-registered fingerprint returns the same installation instead of creating a new one.
- For `license_key` grants, the response also carries the plan's **entitlements** so the product can gate features locally ([15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md)).
- `entitlement` + `entitlement_signature`: an Ed25519-signed envelope (`apps/licensing/entitlement_signing.py`) a product build can verify against a public key baked into its own release, so a compromised proxy or MITM can't forge an `active` response. Signed on every `active` result from `/activate` and `/validate` (including the `MAINTENANCE_MODE` bypass). Requires `MARKETPLACE_ED25519_PRIVATE_KEY_B64` (env-only, never Setting/DB) — unset it and `entitlement_signature` comes back `""` (dev convenience; a product with a public key configured must treat that as untrusted).
- `token_expires_at` is only the 7-day (default) heartbeat-token refresh deadline. `license_expires_at` is the actual subscription period end or a time-limited grant end; it is `null` for perpetual licenses. Products must show and enforce only `license_expires_at` as **Valid Until**.
