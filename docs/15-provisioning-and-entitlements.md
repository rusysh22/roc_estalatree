# 15 — Provisioning & Entitlements (Generalized Fulfillment)

> The single most important architectural generalization: **Estalatree does not just sell license keys.** What a customer buys is an **Entitlement** that is fulfilled by a pluggable **Provisioner**, producing a **Grant**. A license key is just one kind of Grant. This is what lets us add new product capabilities later without rewriting the core.

## 15.1 The model

```
Plan ──defines──> Deliverable(s)  +  Entitlement(s)
                      │
Order paid ──runs──> Provisioner ──produces──> Grant ──(belongs to)──> Customer / Subscription
                                                  │
                                  lifecycle hooks: suspend / renew / revoke
```

- **Deliverable** — declares *what* a Plan provides (type + config). One Plan may have several.
- **Provisioner** — code that fulfills a Deliverable type. Registered in a **registry** (plugin pattern). Interface:
  - `provision(order) -> Grant`
  - `renew(grant)` · `suspend(grant)` · `resume(grant)` · `revoke(grant)`
- **Grant** — the issued artifact + its lifecycle state, owned by the customer and tied to a Subscription (recurring) or standalone (one-time/free).

## 15.2 Deliverable types (initial set)

| Type | What it produces | Notes |
|------|------------------|-------|
| `license_key` | License + activation token | The OSS-activation core. Uses the activation API ([07-api.md](07-api.md)) and `Installation`/seat model. |
| `credentials` | Generated username + **password** | e.g. provision an account/panel login. Secret shown **once**, stored encrypted. |
| `account` | A user created on an external/self-hosted system | Via outbound API/webhook to that system. |
| `download` | File / installer / release asset | Signed, expiring download URL. |
| `access_link` | Private URL / repo invite | Time-boxed. |
| `api_key` | API token for a service | Rotatable. |
| `manual` | Operator fulfills by hand | For "contact"/enterprise deals. |

Adding a new capability later = **write a new Provisioner + register it**. No change to checkout, billing, or subscription core. (See [19-extensibility.md](19-extensibility.md).)

## 15.3 Entitlements (feature gating)

Best practice (Keygen / feature-flag entitlement model): **do not hardcode features per plan.**

- **Entitlement** = a named capability, e.g. `PRO_EXPORT`, `MAX_PROJECTS=10`, `PRIORITY_SUPPORT`.
- Attached to a **Plan**, inherited by its **Grant(s)**.
- Checked server-side in code: `grant.has_entitlement("PRO_EXPORT")`.
- For `license_key` grants, entitlements are returned in the activation/validation response so the OSS product can gate features locally.

This decouples *what features exist* from *which plan unlocks them* → new features ship without schema migrations.

## 15.4 Lifecycle propagation

Subscription state changes cascade to every Grant via its Provisioner:

| Subscription | Grant action |
|--------------|--------------|
| renewed | `renew()` — extend validity, rotate secrets if configured |
| grace | unchanged (still valid) |
| suspended | `suspend()` — license → suspended, credentials disabled, links revoked |
| cancelled / expired | `revoke()` |
| reactivated (top-up) | `resume()` |

## 15.5 New entities (extends [06-data-model.md](06-data-model.md))

- **Deliverable** — `plan`, `type`, `config (JSON)`.
- **Entitlement** — `key`, `name`, `value (nullable)`; M2M with `Plan`.
- **Grant** — `customer`, `subscription (nullable)`, `deliverable`, `type`, `status` (`active|suspended|revoked|expired`), `payload_ref`, `created_at`.
- **Secret** (for `credentials`/`api_key`) — `grant`, `ciphertext` (encrypted at rest), `revealed_once`, `rotated_at`.
- `License` + `Installation` become the **specialization of the `license_key` Grant** (License links to its Grant).

## 15.6 Security

- Generated secrets (passwords, API keys): cryptographically random, **encrypted at rest**, **shown once**, optional rotation on renewal.
- External provisioning (`account`/`api_key`) via outbound calls is **idempotent** and retried by job; failures surface in System Health.
- All provision/revoke actions write to `AuditLog`.
