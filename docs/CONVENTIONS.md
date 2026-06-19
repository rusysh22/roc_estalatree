# CONVENTIONS — Engineering Standards

> Binding rules for the whole codebase, so any agent/session stays consistent. If existing code conflicts, follow this doc and clean the code up.

## Language (system standard)
- **English is the default language of Estalatree** — code, documentation, and base UI strings.
- User-facing text is authored in English; **Indonesian (and other locales) via Django i18n / gettext** when localization is added (growth stage). No hardcoded non-English strings.
- Identifiers, models, fields, functions, comments: **English**.
- Domain vocabulary & status values: [GLOSSARY.md](GLOSSARY.md).

## Money
- **Whole rupiah as integer** (IDR has no practical subunit). Type: `PositiveBigIntegerField`.
- **No `FloatField`** for money. `Decimal` not used (no cents).
- Ledger is **append-only / immutable**, double-entry-style: every entry stores `balance_after` (and `balance_before` where useful); current balance = `SUM(entries)`.
- Display formatting (`Rp1.000.000`) only in the presentation layer.

## IDs & References
- **Internal PK**: `BigAutoField`.
- **Never expose sequential PKs** in URLs/API. For externally-visible entities, add a prefixed `public_id`: `ord_`, `top_`, `lead_`, etc.
- **License Key**: plain hash `XXXX-XXXX-XXXX` (**no prefix**), Crockford Base32 charset (no ambiguous `I O U 0 1`), random, server-generated, unique (indexed).
- **Product `secret`** (API auth) is separate from the license key; stored hashed when possible.
- **Generated secrets** (`credentials`/`api_key` grants): random, **encrypted at rest**, shown once.

## Time
- `USE_TZ = True`, **store UTC**. Display default **Asia/Jakarta (WIB)**.
- Time fields end in `_at` (`created_at`, `activated_at`, `last_seen`).

## Status & Enums
- Always `models.TextChoices` (not loose strings/ints). Values: lowercase snake (`in_progress`).
- Allowed transitions: [14-state-machines.md](14-state-machines.md).

## Naming
- Models `PascalCase` singular (`LedgerEntry`); fields/functions `snake_case`.
- Booleans prefixed `is_`/`has_`/`auto_`. FKs named by entity (`customer`, `plan`).

## API errors (Django Ninja)
- Consistent envelope: `{ "status": "error_code", "message": "...", "code": "MACHINE_CODE" }`.
- Activation statuses follow [07-api.md](07-api.md). Use correct HTTP codes (400/401/403/404/409/429).

## Idempotency
- Webhooks and money jobs **must be idempotent** (unique `ref` / `idempotency_key`). Calling twice = same effect as once.

## Soft delete
- Avoid deleting business data; use status fields. `LedgerEntry` & `AuditLog` are never updated/deleted.

## Architecture patterns (binding)
- **Fat services, thin views.** Business logic in `<app>/services.py`.
- Money mutations **only** via `wallet/services.py`, atomic (`transaction.atomic()` + `select_for_update()`).
- **Provisioner registry** for anything sold ([15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md)).
- **Entitlement keys** for feature gating — never branch on plan name.
- **Domain events** for cross-feature reactions ([19-extensibility.md](19-extensibility.md)).
- Externalize tunables in `Setting`; wrap external systems (Duitku, WA, provisioned apps) in adapters.

## Config & Secrets
- **Three tiers** (see [23-configuration.md](23-configuration.md)): **(1) `.env`** for secrets + infrastructure + bootstrap (deploy-time); **(2) DB `Setting`** for non-secret business tunables (runtime, Superadmin-editable, no restart); **(3) per-record JSON** (`Plan.config`, etc.).
- `django-environ`; settings `config/settings/{base,dev,prod}.py`. `.env.example` lists **Tier 1 only**, committed without real values. **No credentials in repo.**
- **Secret trap:** gateway credentials are Superadmin-configurable but secret — keep in `.env`, or if UI-editable, store in an **encrypted Setting field** (Fernet/KMS), access audited. Never plaintext in the DB.
- **Tier 2 guardrails:** defaults in code (Setting stores overrides only); typed accessors + validation; cache reads + invalidate on save; audit changes to money/security settings.

## Logging
- Structured logs. Must log: incoming webhooks, activation attempts, balance mutations, renewal jobs.

## Testing
- `pytest` + `pytest-django`. **Mandatory tests**: money paths, webhooks (success/duplicate/invalid), activation (seat/expired/revoked), renewal (success/fail/grace). Invariant: `Wallet.balance == SUM(ledger)`. Every bug fix adds a regression test.

## Migrations & Commits
- Always commit migrations with model changes; never edit deployed migrations.
- Commit format: `<area>: <summary>` (e.g. `wallet: add atomic debit service + tests`).
- Work on feature branches; small, focused commits; never push directly to `main`.

## CI & Quality Gates
- **CI (GitHub Actions)** runs on every push/PR: lint (black/ruff/isort) + `pytest` + `python manage.py makemigrations --check --dry-run` + dependency audit (`pip-audit`).
- **Dependency lockfile** with pinned versions (tool: **uv**) — reproducible builds.
- **Pre-commit** includes secret scanning (gitleaks / detect-secrets) in addition to formatters.
- **Permanent gates** (must stay green): money invariant test (`Wallet.balance == SUM(ledger)`), and the **golden-path smoke test** (top-up → buy → activate → renew, against Duitku sandbox).
- Test data via **factory_boy**. Error tracking via **Sentry**; structured logging from day one.

## UI Icons & Assets
- **No emoji as UI icons.** Use a single SVG icon set: **Heroicons** (MIT, pure SVG, no JS), rendered as **inline SVG or an SVG sprite** served locally.
- No icon fonts, no runtime-JS icon libraries. Icons are cacheable static assets.
- Keep assets lightweight; prefer SVG; lazy-load images where sensible.
- Avoid emoji in docs too (use plain text labels).
