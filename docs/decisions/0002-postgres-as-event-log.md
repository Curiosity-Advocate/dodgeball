# ADR-0002 — PostgreSQL as the event log

> **Context:** Expands overview.md §3. Driven by: `NFR-2`, `NFR-8`, `READ-*`.

**Status:** Accepted. Adopted in v1.0.

---

## Context

Event sourcing (ADR-0001) needs a durable, ordered append-only store. The obvious
reflex is to reach for a dedicated event-streaming system, but the workload here is
unusual: writes are **human-paced** (a few scoring events per match per minute),
while the demanding side is reads and fan-out. The system also needs relational
queries (standings, match listings) and the accounts, ideally without operating a
second datastore.

## Decision

Use a **PostgreSQL append-only table** (`match_events`) as the event log. The same
database holds the projections (`match_state`, `standings`) and the accounts. A
monotonic per-match `version` provides ordering, and replay is an ordinary
`WHERE match_id = ? AND version > ?` query.

## Consequences

**Positive.**

- Transactions make "append event + update projection" atomic.
- One store for the log, projections, and accounts — nothing to keep in sync across
  systems, simple to operate (`NFR-2`).
- Standard relational reads for standings and listings (`READ-*`).
- High availability is cheap because the durable surface is small (`NFR-8`).

**Negative.**

- Postgres is not a streaming broker; very high write throughput would eventually
  need something else — but that capability is unnecessary at this write rate.

## Alternatives considered

- **Kafka / EventStoreDB.** Built for high append throughput and native streaming —
  overkill for human-paced writes, and they would *still* require a separate
  database for the relational projections, adding a second system to operate.
- **A NoSQL document/wide-column store.** Cannot serve the relational reads
  (standings, filtered listings) the product needs.

The migration door to a streaming system is kept open deliberately, behind the
`EventStore` abstraction (ADR-0003), so this choice is not a one-way door.
