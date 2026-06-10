# ADR-0004 — Optimistic concurrency via per-match version

> **Context:** Expands overview.md §5. Driven by: multiple-scorekeepers (v2.0 scope, functional.md *Deferred*).

**Status:** Accepted. Planned for v2.0 (not enforced in v1.0).

---

## Context

In v1.0 a match has exactly one scorekeeper, so `version` is used only as the
ordering/replay cursor and the idempotency key handles retries; there is no
write-time concurrency check. v2.0 introduces multiple scorekeepers per match
(e.g. a primary and a backup). Two scorekeepers can then form an action against the
same current `version`, and without coordination the log could record lost or
mis-ordered updates.

## Decision

Reuse the per-match `version` as **optimistic-concurrency control** for v2.0:

1. A writer reads current state at **version N**.
2. It submits its append with **`expected_version = N`**.
3. The server, in one transaction, compares against the match's current version:
   still N → accept, assign **N+1**, commit; already advanced → reject **409**.
4. The rejected writer refetches (now N+1), reconciles, and retries with the new
   expected version.

The existing `UNIQUE (match_id, version)` constraint is the final database backstop
against two appends claiming the same version.

## Consequences

**Positive.**

- Concurrent writers are serialised; the log stays correctly ordered with nothing
  lost or interleaved wrongly.
- It reuses the column already present for the cursor — no new schema.
- Correctness is ultimately enforced by the database, not just application logic.

**Negative.**

- Clients must handle `409` with a refetch-and-retry loop.
- The write API gains an `expected_version` field in v2.0.

## Alternatives considered

- **Pessimistic locking** (lock the match while a scorekeeper edits). Fragile —
  holds a lock across human think-time and blocks the other writer; poor fit for a
  live, intermittently-connected client.
- **Last-write-wins.** Silently loses or overwrites a concurrent update —
  unacceptable for a score of record.
- **Remain single-writer forever.** Rejected because v2.0 explicitly wants a backup
  scorekeeper for resilience.
