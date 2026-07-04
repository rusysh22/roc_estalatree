# 24 — Deployment (Docker + nginx + Let's Encrypt)

> How Estalatree is built and served in production on a single VM, at **https://berlanggan.web.id**. Written after standing up the first deployment on 2026-07-03.

## 1. Architecture

One Docker Compose stack, one VM. nginx terminates TLS and reverse-proxies to gunicorn; Postgres/Redis are containers, not managed services.

```
Internet
   │  :80 / :443
   ▼
┌─────────┐   /static/, /media/ (served directly from volumes)
│  nginx  │───────────────────────────────────────────────┐
└────┬────┘                                                │
     │ proxy_pass :8000                                    │
     ▼                                                      ▼
┌─────────┐        ┌─────────┐        ┌─────────┐   static_data / media_data
│   web   │◄──────►│   db    │        │  redis  │   (named volumes)
│gunicorn │        │postgres │        └────┬────┘
└─────────┘        └─────────┘             │
     ▲                                     │
     │              ┌─────────┐            │
     └──────────────┤ worker  │◄───────────┘
                     │ celery  │
                     └─────────┘
                     ┌─────────┐
                     │  beat   │  (celery periodic scheduler)
                     └─────────┘
                     ┌─────────┐
                     │ certbot │  (renews cert every 12h)
                     └─────────┘
```

| Service | Image | Role |
|---|---|---|
| `web` | built from `Dockerfile` | Django app served by gunicorn (3 sync workers), port 8000 internal only |
| `worker` | same image | Celery worker — billing/notifications async tasks |
| `beat` | same image | Celery beat — periodic tasks (`django_celery_beat` DB scheduler) |
| `db` | `postgres:16-alpine` | Primary datastore. Host port `5434` → container `5432` |
| `redis` | `redis:7-alpine` | Cache + Celery broker/result backend |
| `nginx` | `nginx:alpine` | TLS termination, static/media serving, reverse proxy. Ports `80`/`443` |
| `certbot` | `certbot/certbot` | Long-running loop: `certbot renew` every 12h |

## 2. Files

| File | Purpose |
|---|---|
| `Dockerfile` | Single image for `web`/`worker`/`beat`. Uses `uv` to install deps from `pyproject.toml`/`uv.lock`, then runs as `python:3.12-slim` with gunicorn. |
| `docker-entrypoint.sh` | Used by `web`: wait for Postgres → `migrate` → `collectstatic` → exec CMD (gunicorn). |
| `docker-entrypoint-worker.sh` | Used by `worker`/`beat`: wait for Postgres → exec CMD. No migrate/collectstatic (avoids 3-way race on the shared static volume). |
| `docker-compose.yml` | All 7 services + named volumes (`postgres_data`, `redis_data`, `static_data`, `media_data`). |
| `nginx/conf.d/app.conf` | HTTP→HTTPS redirect + ACME challenge location on `:80`; TLS + reverse proxy + static/media `alias` on `:443`. Domain is hardcoded to `berlanggan.web.id`. |
| `certbot/conf/options-ssl-nginx.conf` | Hand-written recommended TLS cipher/protocol config (Mozilla intermediate-ish). Committed — not a secret. |
| `init-letsencrypt.sh` | One-time bootstrap: dummy self-signed cert → start nginx → request real cert via webroot → reload nginx. Idempotent (skips if `certbot/conf/live/<domain>` already exists). |
| `.env` | Real secrets/config for the stack. **Not committed** (`.gitignore`). See §4. |
| `.env.example` | Template — copy to `.env` and fill in for a new deployment. |

`certbot/conf/` and `certbot/www/` are gitignored — they hold the live private key, the Let's Encrypt account key, and ACME challenge files, all regenerated per-deployment by `init-letsencrypt.sh`.

## 3. First-time setup on a new host

```bash
# 1. Install Docker Engine + Compose plugin (official apt repo), enable the daemon.
# 2. Confirm DNS: the domain's A record must already point at this host's public IP —
#    Let's Encrypt validates ownership by fetching a file over plain HTTP on port 80.
getent hosts berlanggan.web.id

# 3. Create .env from .env.example, fill in real secrets:
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # DJANGO_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(40))"   # PROVISIONING_SECRET_KEY
# Set DJANGO_SETTINGS_MODULE=config.settings.prod, DJANGO_ALLOWED_HOSTS=berlanggan.web.id,
# DATABASE_URL=postgres://estalatree:estalatree@db:5432/estalatree (service name "db", not localhost),
# REDIS_URL=redis://redis:6379/0

# 4. Build and start the app tier first (nginx isn't up yet, cert doesn't exist).
sudo docker compose up -d db redis web worker beat

# 5. Bootstrap the TLS cert (generates dhparams, dummy cert, real cert, starts nginx).
sudo ./init-letsencrypt.sh

# 6. Start the renewal loop.
sudo docker compose up -d certbot
```

## 4. Key `.env` values (production)

| Var | Value used | Note |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` | `wsgi.py` also defaults to this, but set it explicitly for `manage.py`/Celery. |
| `DJANGO_DEBUG` | `False` | |
| `DJANGO_ALLOWED_HOSTS` | `berlanggan.web.id` | Comma-separated if adding `www.` or more hosts later. |
| `DATABASE_URL` | `postgres://estalatree:estalatree@db:5432/estalatree` | Container-to-container hostname `db`, **internal** port 5432 (the `5434` mapping in compose is only for host-side debugging access). |
| `REDIS_URL` / `CELERY_BROKER_URL` | `redis://redis:6379/0` | Container hostname `redis`. |
| `DUITKU_CALLBACK_URL` | `https://berlanggan.web.id/billing/webhook/duitku/` | Must be publicly reachable HTTPS for the gateway to call back. |

`DUITKU_MERCHANT_CODE`/`DUITKU_API_KEY` (sandbox) and `EMAIL_HOST*` were filled in on 2026-07-04 — SMTP is smtp.sumopod.com, port 465/SSL (`EMAIL_USE_SSL=True`, not `EMAIL_USE_TLS`; `base.py` now reads both `EMAIL_USE_TLS`/`EMAIL_USE_SSL` and the rest of the `EMAIL_HOST*` vars from env, which it previously did not). Still blank: `GOOGLE_CLIENT_ID/SECRET`, `SENTRY_DSN`.

## 5. Redeploying after a code change

The image bakes the app source in at build time (`COPY . .` — no source bind-mount), so **editing files on the host does nothing until the image is rebuilt**. Run:

```bash
./deploy.sh
```

which does `git pull` → rebuild `web`/`worker`/`beat` → recreate them → wait for gunicorn to actually respond → reload nginx → curl `https://berlanggan.web.id/` to confirm, falling back to a full nginx restart and printing logs if anything's still broken.

`docker-entrypoint.sh` re-runs `migrate` and `collectstatic` on every `web` start, so new migrations/static assets ship automatically.

**nginx must be reloaded after every `web` recreate.** `nginx/conf.d/app.conf` has `upstream django { server web:8000; }` — nginx resolves that hostname once at start/reload and caches the IP. Recreating the `web` container gives it a new IP on the `berlanggan_default` network; until nginx reloads, it keeps proxying to the old (now-gone) IP and every request 502s with `connect() failed (111: Connection refused)` in the nginx logs. `deploy.sh` handles this automatically (`nginx -s reload`, or a full restart if reload alone doesn't clear it) — this is why the manual `git pull` + rebuild sequence above is no longer the recommended path.

## 6. Certificate renewal

The `certbot` service runs `certbot renew` every 12h in a loop; it's a no-op until the cert is within 30 days of expiry. Current cert: issued 2026-07-03, expires **2026-10-01**. nginx reloads its config every 6h (background loop in the `nginx` service's command) to pick up a renewed cert without a restart.

## 7. Three bugs found and fixed while standing this up

These were pre-existing app bugs that only surface once you deploy behind a real reverse proxy with a real domain — worth knowing so they aren't reintroduced:

1. **`ALLOWED_HOSTS` parsed as a raw string, not a list** (`config/settings/base.py`). `env("DJANGO_ALLOWED_HOSTS", default=[])` doesn't match the `Env()` schema key (`ALLOWED_HOSTS`, not `DJANGO_ALLOWED_HOSTS`), so django-environ returned the literal string — Django then validated the Host header character-by-character. Fixed with `env.list(...)`.
2. **Missing `gunicorn` and `requests` dependencies** (`pyproject.toml`). `django-allauth[google]==65.18.0` doesn't actually bundle `requests` under its `google` extra (installer warns but doesn't fail) — the app crashed on boot with `ModuleNotFoundError: No module named 'requests'`. Added both as direct dependencies; `uv.lock` regenerated to match.
3. **Infinite HTTPS redirect loop** (`config/settings/prod.py`). `SECURE_SSL_REDIRECT = True` checks `request.is_secure()`, which is always `False` when TLS is terminated at nginx and forwarded to gunicorn over plain HTTP — Django redirected every request to `https://` even though it was already HTTPS. Fixed by adding `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`, matching nginx's `proxy_set_header X-Forwarded-Proto $scheme;`.

## 8. Known gaps / not yet done

- No CI/CD — deploys are manual (`git pull` + rebuild) on the host, no automated pipeline.
- No backups configured for `postgres_data` (ties into B-11 in [reviews/deep-evaluation.md](reviews/deep-evaluation.md) — ledger backups are a P1 item).
- `www.berlanggan.web.id` is not in `ALLOWED_HOSTS` and has no cert SAN — requests to it get a clean `400 DisallowedHost`, not a crash, but it isn't served. Add it to both `DJANGO_ALLOWED_HOSTS` and re-run certbot with `-d www.berlanggan.web.id` if a `www` redirect is wanted.
- Redis-backed rate-limit cache and money-flow tests on Postgres (rather than SQLite) are still open ops items — see B-11.
