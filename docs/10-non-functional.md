# 10 — Non-Functional & Quality Standards

## Security
- Activation tokens are **signed** (HMAC/asymmetric); secret in env, not the repo.
- Activation API: **rate limiting** + `license_key`+`secret` auth.
- Duitku webhook: **signature verification** + **idempotency**.
- Passwords: Django default hashing. HTTPS in production. CSRF on forms.
- Secrets via `django-environ` / env vars. **No** hardcoded credentials.

## Money Integrity (critical)
- All balance mutations go through an atomic **service layer** (`transaction.atomic()` + `select_for_update()`).
- **Idempotency** `ref` on every LedgerEntry.
- `LedgerEntry` & `AuditLog` are **immutable** (no update/delete).
- **Invariant test**: `Wallet.balance == SUM(ledger)` always holds.
- Money as **whole rupiah integer** (`PositiveBigIntegerField`), **not** Decimal/float — see [CONVENTIONS.md](CONVENTIONS.md).

## Audit
- Sensitive actions (refund, adjustment, setting change, revoke) → automatic **AuditLog**.

## Background Jobs
- **Celery** (or Django-Q) + **Redis**.
- Jobs: renewal (auto-deduct), reminders (H-3/H-1), async webhook processing, notification sending, expired token/heartbeat cleanup.
- Jobs must be **idempotent & retry-safe**.

## Observability
- Structured logging. Error tracking (e.g. Sentry).
- Log activation attempts & webhooks for audit/abuse.

## Code Quality (mandatory standard)
- **black** + **ruff** + **isort** (pre-commit).
- **Type hints** in services & schemas (Pydantic/Ninja).
- Pattern: **fat services, thin views/models**. Business logic in `services.py`, not in views.
- **Always include & commit migrations**.
- **Mandatory tests** for: money paths (wallet/ledger), webhooks, activation/seat limits, renewal.
- Split settings: `base / dev / prod`.

## Risks & Open Questions (tracked in STATUS.md)
- **Installation fingerprint** strategy (stable vs anti-forgery vs hardware change).
- **WA gateway** choice (Fonnte/Wablas/official) — cost & reliability.
- **PPN/tax** on invoices.
- **Grace period** length ideal for offline tolerance.
- Recurring depends on customer top-up discipline + reminder effectiveness.
