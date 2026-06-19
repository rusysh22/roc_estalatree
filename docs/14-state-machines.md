# 14 — State Machines (Status Transitions)

> Only the transitions below are **valid**. Any other transition must be rejected in the service layer. Statuses use `TextChoices` (see [GLOSSARY.md](GLOSSARY.md)).

## TopUp
```
pending ──pay(webhook)──> paid        (→ credit balance)
pending ──expire────────> expired
pending ──fail──────────> failed
```
`paid` is final. Cannot return to `pending`.

## Order
```
pending ──balance sufficient & deducted──> paid     (→ issue grant)
pending ──insufficient/failed────────────> failed
paid    ──refund approved────────────────> refunded (→ credit balance)
```

## Subscription
```
        ┌──────────────── renewal success ────────────────┐
        v                                                  │
active ──due & balance short──> grace ──grace over & still short──> suspended
active ──auto_renew off & period ends───────────────────────────────> cancelled
grace  ──top-up & renew───────> active
suspended ──top-up & renew────> active
```
- `grace` = past due but still within the grace window.
- `cancelled` is final (this subscription is done; buying again = a new subscription).

## License
```
active ──subscription suspended──> suspended ──subscription active again──> active
active ──one_time, no sub───────> (stays active forever)
active ──abuse / manual─────────> revoked        (final)
active ──period ends without renewal──> expired
suspended ──reactivate──────────> active
```
- A recurring license follows its Subscription status.
- A one-time license never `expired` (lifetime), but can be `revoked`.

## Installation
```
(new) ──activate──> active ──deactivate / move machine──> deactivated
active ──license revoked/suspended──> (effectively invalid; physical status stays, validation rejects)
```
- `deactivated` frees a `seat_limit` slot.

## Implementation notes
- Each valid transition is a **service method** (e.g. `subscription_renew()`, `license_suspend()`), not a manual field set.
- Every important transition (suspend, revoke, refund) writes an `AuditLog` and emits a domain event.
- Job-triggered transitions (renewal/grace) must be **idempotent**.
