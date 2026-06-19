# Phase 7 Review — Notifications

**Date:** 2026-06-18 · **Reviewer:** assistant (review-only; no code changed)
**Commit reviewed:** `312b49f feat: Phase 7 — Notifications` (+ `3691bd7` docs)
**Also confirmed:** `b270419` applied Phase 6 fixes (SUSPENDED reactivation, auto_renew=False expiry).
**Verdict:** Clean. Pluggable WA channel (`Protocol` + Console/Fonnte via `WA_BACKEND` Setting), event handlers dispatching async Celery tasks (fire on_commit, non-blocking), tasks with retries/`acks_late`, H-3/H-1 reminder job with tolerant windows + shortfall calc (closes Phase 6 M3). One HIGH (recurring secret trap) + reminder dedup/cost items.

## What's good (keep)
- Channel abstraction; adding a gateway = implement `.send()` + register in `_BACKENDS`.
- Handlers subscribe via `@on`, dispatch `.delay()`; each wrapped in try/except (never crash the path).
- Email + WA delivery tasks: retries, `acks_late`.
- Reminder source for H-3/H-1 (the missing Phase 6 M3 signal).

---

## HIGH

### H1. WA gateway token (`WA_TOKEN`) read from plaintext Setting — secret trap
`FonnteBackend.send()` reads `Setting.get("WA_TOKEN")` — a secret API token stored plaintext in the DB. Same violation fixed for the Duitku key in Phase 3 H1. Per [23-configuration.md](../23-configuration.md), gateway secrets go in env or an encrypted field — not plaintext Setting (`WA_BACKEND` may stay in Setting; `WA_TOKEN` must not).
- **Action:** read `WA_TOKEN` from env (or encrypted Setting field).

---

## MEDIUM

### M1. No notification dedup/idempotency → duplicate messages
`send_renewal_reminders` is an hourly job with `acks_late=True` + retries; a mid-run worker crash → retry re-sends to everyone in the window. Retried `deliver_whatsapp`/`deliver_email` re-send after a gateway already delivered. Nothing records "already sent."
- **Action:** add a `NotificationLog` with a dedup key (e.g. `reminder:{sub}:{period_end}:{H3|H1}`, `event:{name}:{ref}`) checked before send.

### M2. Reminders sent even when balance is sufficient → spam + WA cost
`dispatch_renewal_reminders` sends both H-3 and H-1 to all active subs, including a "balance is enough" message. Two "all-good" messages per cycle to every customer is noisy and burns WA credits. Journey step 8 emphasises actionable reminders (top-up CTA).
- **Action:** send only when `shortfall > 0` (or limit the "sufficient" message to a single H-1).

### M3. Emoji in WA/email message bodies vs the no-emoji standard — decide
Messages use emoji (status glyphs). Gray area: the no-emoji standard targets **UI icons** (use SVG); WA bodies are content where emoji are conventional and SVG is impossible. Given the user's broad anti-emoji preference, this needs a decision.
- **Action (user decision):** exempt notification bodies (content, not UI chrome), or switch to plain text. Not changed unilaterally.

---

## LOW
- Reminder windows are fragile to scheduler drift (gap >1h → missed; late run → duplicate) — the M1 dedup also fixes this.
- Confirm the reactivation event (Phase 6 M1): if it reuses `subscription.renewed`, the message says "renewed" — consider a dedicated "access restored" message.
- `normalize_number` applied inconsistently (handlers normalize, reminders don't) — harmless, `send_whatsapp` re-normalizes (idempotent).
- No customer notification preferences/opt-out yet (fine, Stage 2).

---

## Suggested action mapping
| Item | When |
|------|------|
| H1 WA_TOKEN out of plaintext Setting | Now |
| M1 NotificationLog dedup | Now (reminders especially) |
| M2 reminder only on shortfall | Now |
| M3 emoji-in-messages decision | User decision |
| LOW | Stage 2 / as convenient |
