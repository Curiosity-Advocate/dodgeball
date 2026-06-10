# ADR-0010 — Snapshot + replay reconnect

> **Context:** Expands overview.md §6. Driven by: `RT-3`, `RT-4`, `NFR-5`, `NFR-7`.

**Status:** Accepted. Adopted in v1.0.

---

## Context

The headline guarantee is that a spectator never misses an update across a
disconnect (`NFR-5`), over a fan-out transport that is only best-effort (`NFR-7`).
A reconnecting client must catch up, but two situations differ sharply: it may know
exactly which version it last applied (a brief drop), or it may not — a fresh page
load, or an absence so long that replaying every missed event would be wasteful.

## Decision

Use the per-match `version` as the recovery cursor, with two paths:

- **Replay (small, known gap).** The client sends its `last_version`; the server
  returns events with `version` greater than it (`GET …/events?since=`), then
  resumes the live stream.
- **Snapshot (unknown or large gap).** The client fetches `…/snapshot` — the current
  state plus the `version` it corresponds to — adopts it wholesale, and continues
  from there.

The client applies events strictly in `version` order, buffers out-of-order
arrivals, requests replay on a detected gap, and ignores versions it has already
applied.

## Consequences

**Positive.**

- Completeness is guaranteed regardless of transport drops — the durable log is the
  authority (`NFR-5`, `NFR-7`).
- Recovery cost is bounded: a snapshot caps the work for a long absence so a client
  never replays thousands of events.
- The snapshot is self-describing (state + cursor), so a brand-new viewer uses the
  same mechanism as a reconnecting one.

**Negative.**

- Clients must implement the cursor, ordering, replay, and snapshot logic.
- Projections must expose a snapshot read.

## Alternatives considered

- **Always replay from the start.** Unbounded cost for a long match; needless work
  when a snapshot answers directly.
- **Snapshot only, no replay.** Wasteful for a one-event gap, and gives no way to
  fill a precise mid-stream gap detected by version.
- **Rely on transport redelivery.** A best-effort fan-out cannot guarantee
  redelivery; the log, not the transport, must be the source of recovery.
