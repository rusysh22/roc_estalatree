# 11 — Tech Stack & Project Structure

## Stack
- **Backend/Web**: Django (LTS) + **Django Ninja** (typed API, FastAPI-style).
- **DB**: PostgreSQL.
- **Frontend**: HTMX + Tailwind (server-rendered, dynamic without an SPA).
- **Admin**: Django Admin (polished) for Superadmin & Admin.
- **Async**: Celery (or Django-Q) + Redis.
- **Auth**: django-allauth — email/password + Google SSO; Groups/Permissions for admin RBAC ([16-auth-and-sso.md](16-auth-and-sso.md)).
- **Config**: django-environ (env-based, settings `base/dev/prod`).
- **Dependencies**: **uv** (lockfile, pinned versions).
- **Tooling**: black, ruff, isort, pytest + pytest-django, factory_boy, pre-commit (incl. gitleaks/detect-secrets).
- **CI**: GitHub Actions (lint + tests + `makemigrations --check` + pip-audit).
- **Observability**: Sentry + structured logging.
- **Icons/UI**: Heroicons (SVG, inline/sprite), Tailwind — no emoji ([CONVENTIONS.md](CONVENTIONS.md)).
- **Dev infra**: Docker Compose (db + redis) for parity.

## Project Structure (planned)
```
estalatree/
├── manage.py
├── pyproject.toml            # deps + tooling config
├── docker-compose.yml        # postgres + redis (dev)
├── .env.example
├── config/                   # project (settings, urls, celery)
│   ├── settings/ (base.py, dev.py, prod.py)
│   ├── urls.py
│   └── celery.py
├── apps/
│   ├── accounts/             # Customer, SellerProfile, auth
│   ├── wallet/               # Wallet, LedgerEntry, services (MONEY)
│   ├── catalog/              # Product, Plan, Entitlement
│   ├── billing/              # Order, TopUp, Subscription, webhook
│   ├── provisioning/         # Deliverable, Grant, Provisioner registry
│   ├── licensing/            # License, Installation, activation API
│   ├── storefront/           # StorePage, Block (link-in-bio), themes, public pages
│   ├── console/              # Operator Console (HTMX) — Operator/Superadmin daily ops
│   ├── dashboard/            # Customer Dashboard (HTMX) — purchases, licenses, devices
│   ├── crm/                  # Lead
│   ├── notifications/        # WA, email, templates
│   └── core/                 # AuditLog, Setting, events, base models, utils
│   # 4 surfaces (see 20-ui-information-architecture.md):
│   #   /admin/    Django Admin   — Superadmin only
│   #   /console/  Operator Console (app: console)
│   #   /dashboard/ Customer Dashboard (app: dashboard)
│   #   / , /<slug> Storefront (app: storefront)
├── api/                      # Django Ninja router (/v1)
├── templates/                # HTMX + Tailwind
├── static/
└── tests/
```

## App → document map
| App | Reference doc |
|-----|---------------|
| accounts | [02-roles.md](02-roles.md), [16-auth-and-sso.md](16-auth-and-sso.md) |
| wallet | [03-core-concepts.md](03-core-concepts.md) §3.1 |
| catalog | [04-products-pricing.md](04-products-pricing.md), [17-product-packaging.md](17-product-packaging.md) |
| billing | [05-flows.md](05-flows.md), [08-integrations.md](08-integrations.md) |
| provisioning | [15-provisioning-and-entitlements.md](15-provisioning-and-entitlements.md) |
| licensing | [03-core-concepts.md](03-core-concepts.md) §3.2, [07-api.md](07-api.md) |
| storefront | [20-ui-information-architecture.md](20-ui-information-architecture.md) |
| crm | [09-features.md](09-features.md) §9.2 |
| notifications | [08-integrations.md](08-integrations.md) |
| core | [06-data-model.md](06-data-model.md), [10-non-functional.md](10-non-functional.md), [19-extensibility.md](19-extensibility.md) |
