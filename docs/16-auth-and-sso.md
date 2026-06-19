# 16 — Authentication & SSO

> Library: **django-allauth** (the standard for Django consumer/SaaS auth; 50+ social providers, email verification, account management). Enterprise SSO (SAML/SCIM) is intentionally **out of scope** for now — revisit if B2B demand appears.

## 16.1 Methods

| Audience | Methods |
|----------|---------|
| **Customer** | Email + password (with verification), **Google SSO** (OAuth2). Extensible to GitHub/etc. via allauth. |
| **Admin / Superadmin** | Django admin login + **2FA** (allauth MFA or django-otp) — required for accounts that touch money. |
| **Installation (product)** | Not a user session. Authenticated by `license_key` + `secret` at the API ([07-api.md](07-api.md)). |

## 16.2 Google SSO — best-practice config (from research)

- OAuth2 with **PKCE enabled**.
- Scopes minimal: `profile`, `email`. `access_type = online`.
- **Client ID/secret from environment** (never in repo) — see [CONVENTIONS.md](CONVENTIONS.md).
- Authorized redirect URIs per environment (dev/prod).
- On first Google login → create/link Customer; if email matches existing account, link (allauth handles).

## 16.3 Account rules

- Email verification required for password signups before purchase/top-up.
- Password reset, change password, manage connected social accounts — all via allauth.
- Notification contact (WA number, email) lives on the Customer profile, editable.
- One Customer = one Wallet; SSO and password can coexist on the same account.

## 16.4 Security baseline

- HTTPS only in production; secure + httponly session cookies; CSRF on forms.
- Rate-limit login & password reset.
- 2FA mandatory for Admin/Superadmin (sensitive: refunds, adjustments, gateway config).
- All admin auth events → `AuditLog`.

## 16.5 Multi-tenant-ready

Customer accounts belong to the platform. When the marketplace opens, a **Seller** role becomes an Admin subtype scoped to its own data; auth stack (allauth) is unchanged.

## 16.6 Future (not now)

- Additional social providers (GitHub, Apple) — trivial via allauth.
- Enterprise OIDC/SAML SSO + SCIM — only if selling to organizations.
