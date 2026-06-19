# 07 — Activation API (Django Ninja)

Base path: `/v1`. Format: JSON. Product auth: `license_key` + `secret` (header `X-Estalatree-Secret`). Rate limited. Responses are signed.

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
{ "status": "active", "token": "<signed>", "expires_at": "2026-07-01T00:00:00Z", "grace_days": 3 }
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
{ "status": "active|expired|revoked|suspended", "token": "<signed?>", "expires_at": "..." }
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
