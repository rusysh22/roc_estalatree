# 13 — Agent Handoff Guide

> For **any AI agent / developer** continuing the Estalatree implementation (e.g. when a previous session ran out of tokens). Goal: continue **without losing context** and without breaking the standards.

## First steps on entry (mandatory, in order)
1. Read [README.md](README.md) → the document map.
2. Read this document fully.
3. Open [STATUS.md](STATUS.md) → find the first **unchecked** phase & task.
4. Open [12-build-plan.md](12-build-plan.md) → read that phase's detail (DoD + mandatory tests).
5. Open the reference docs the phase points to (see the app→doc map in [11-tech-stack.md](11-tech-stack.md)).
6. `git log --oneline -15` + `git status` → understand what already exists.
7. Only then write code. **Do not** skip phases.

## Source of Truth
- **Spec** = the `docs/` folder. If code conflicts with docs, **docs win** unless the docs are clearly stale — if stale, **update the docs in the same PR**.
- **Progress** = [STATUS.md](STATUS.md). Always update it after finishing a task.
- **Design decisions** are final ([DECISIONS.md](DECISIONS.md)): stack, balance model, single-merchant multi-ready, recurring = balance auto-deduct, generalized provisioning, entitlements, allauth/Google SSO, English standard. **Do not change** without user instruction.

## Definition of Done (per task)
A task is done ONLY when:
- [ ] Code matches the reference doc.
- [ ] Migrations created & included (if models changed).
- [ ] The phase's **mandatory tests** are written & **green**.
- [ ] Lint green (black/ruff/isort).
- [ ] No hardcoded secrets (use env).
- [ ] [STATUS.md](STATUS.md) updated (check off + short note).
- [ ] Small, descriptive commit.

## Code Standards (do not violate)
- Follow **[CONVENTIONS.md](CONVENTIONS.md)** (language, money, IDs, time, status, errors, tests) & **[GLOSSARY.md](GLOSSARY.md)** (naming). Status transitions: **[14-state-machines.md](14-state-machines.md)**.
- **Money** only via `wallet/services.py`. Never change `balance` directly in views/models. Atomic + idempotent. See [10-non-functional.md](10-non-functional.md).
- `LedgerEntry` & `AuditLog` are **immutable**.
- **Fat services, thin views.** Business logic in `services.py`.
- New thing to sell → a **Provisioner**, not a checkout special case. New feature gate → an **Entitlement** ([15](15-provisioning-and-entitlements.md), [19](19-extensibility.md)).
- Type hints in services & Ninja schemas; settings `base/dev/prod`; config via env.
- Money = whole rupiah integer, **not** float.

## Module Boundaries (so parallel agents don't collide)
Each app has a single responsibility ([11-tech-stack.md](11-tech-stack.md)). Cross-app communication via **service functions** + **domain events**, not arbitrary cross-app model imports. Dependency order: `core → accounts → wallet → catalog → billing → provisioning/licensing → notifications → crm`.

## Commit Convention
```
<area>: <summary>      # e.g. wallet: add atomic debit service + tests
```
Area = app/phase name. Include migrations & tests in the relevant commit.

## When unsure / a decision is needed
Don't guess anything that changes product direction (WA gateway, tax, fingerprint strategy, business model). Record it as an **Open Question** in [STATUS.md](STATUS.md) and ask the user, or pick the safest default and mark `TODO(decision)` in code.

## Not yet decided (don't silently assume)
See [STATUS.md](STATUS.md) → "Open Questions": WA gateway, fingerprint strategy, PPN/tax, grace period length, Duitku credentials, default auto-renew, secret encryption, external provisioning targets.
