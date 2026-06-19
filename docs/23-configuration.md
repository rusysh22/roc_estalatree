# 23 — Configuration Management

> Where each piece of configuration lives, and why. The rule prevents two failures: leaking secrets into the database, and forcing a redeploy for things a Superadmin should change at runtime.

## The three tiers

| Tier | Store | Changes need | Editable by | Examples |
|------|-------|--------------|-------------|----------|
| **1. Environment** | `.env` / env vars | Deploy + restart | DevOps (deploy) | `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `ALLOWED_HOSTS`, `DEBUG`, signing key, Sentry DSN, **gateway secrets** |
| **2. DB Setting** | `Setting` model | None (runtime) | Superadmin (UI) | token TTL, grace days, min top-up, bonus rules, default auto-renew, maintenance mode, panic global-grace, notification templates, suggested top-up packages, platform fee |
| **3. Per-record config** | model JSON fields | None (per record) | Operator (UI) | `Plan.config`, `Deliverable.config`, `StorePage.theme`, `Block.config` |

### Why Tier 1 cannot move to the DB
1. **Security blast radius** — DB-stored secrets end up in backups, dumps, logs, and the admin UI; rotation becomes risky.
2. **Bootstrap (chicken-and-egg)** — some config is needed *before* the DB is reachable (`DATABASE_URL`, `SECRET_KEY`). It cannot be read from the DB.

### Why Tier 2 belongs in the DB
It is **non-secret business tuning** that the Superadmin should change at runtime **without a redeploy** — exactly the `Setting` model's purpose.

---

## The secret trap (important)

Gateway credentials (Duitku key/secret, WA gateway key) are **Superadmin-configurable but secret**. Do **not** store them as plaintext in `Setting`. Two acceptable options:

1. **Keep them in `.env`** (simplest, safest), or
2. If they must be UI-editable, store in an **encrypted Setting field** (Fernet / KMS-backed), with **access audited**. Never plaintext in the DB.

---

## Guardrails for Tier 2 (DB Setting)

1. **Defaults in code; `Setting` stores only overrides** — an empty DB still boots, and the full set of settings is always discoverable from code.
2. **Typed accessors + validation** — reject invalid values (e.g. `grace_days = "banana"`); coerce to the right type.
3. **Cache reads + invalidate on save** — this is what makes "no restart" cheap; do not query the DB on every request. Invalidate the cache when a value changes.
4. **Audit changes** — record who changed money/security-adjacent settings (bonus, fee, grace, TTL) and from what to what, in `AuditLog`.

---

## Tooling recommendation

Consider **django-constance** (DB/Redis-backed, admin-editable, cached, typed) instead of hand-rolling the `Setting` accessor layer — it is mature and built for exactly this. If keeping a custom `Setting`, add the cache + typed + audit layer above.

---

## Implication for `.env.example`

`.env.example` should list **Tier 1 only** (secrets + infrastructure + bootstrap), committed without real values. Business tunables live in `Setting`; do not duplicate them in `.env`.

```
# .env.example (Tier 1 only — illustrative, no real values)
SECRET_KEY=
DEBUG=False
ALLOWED_HOSTS=
DATABASE_URL=
REDIS_URL=
SENTRY_DSN=
DUITKU_MERCHANT_CODE=
DUITKU_API_KEY=
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
WA_GATEWAY_API_KEY=
LICENSE_TOKEN_SIGNING_KEY=
```
