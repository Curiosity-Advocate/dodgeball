# ADR-0003 — EventStore abstraction for Kafka portability

> **Context:** Expands overview.md §3. Driven by: `NFR-15`.

**Status:** Accepted. Adopted in v1.0.

---

## Context

PostgreSQL is the event log (ADR-0002), chosen because the write rate does not
justify a streaming system. That may change if the platform later grows multiple
independent consumers of the event stream. If event-log SQL were scattered across
call sites, moving the log behind an outbox to Kafka would be a wide, risky change.

## Decision

Access the event log **only** through a single `EventStore` interface:

- `append(match_id, event)` — append one event (idempotent, version-assigning),
- `read_since(match_id, version)` — events after a cursor, for replay,
- `snapshot(match_id)` — current state plus its version.

A `PostgresEventStore` implements it for v1.0. No other module reads or writes
`match_events` directly (enforced per [module-boundaries.md](../architecture/module-boundaries.md)).

## Consequences

**Positive.**

- A future Postgres-outbox → Kafka migration is localised to one module; call sites
  are untouched (`NFR-15`).
- The interface is a clean seam for testing (a fake `EventStore` in unit tests).
- Encapsulation of the log is enforced rather than hoped for.

**Negative.**

- One layer of indirection, and a small abstraction to maintain before it is
  strictly needed.

## Alternatives considered

- **Direct SQL at call sites.** Simplest today, but couples every module to
  PostgreSQL and turns a later migration into a sprawling change.
- **Adopt Kafka now.** Premature for the write volume (ADR-0002); this abstraction
  defers that decision without preventing it.
