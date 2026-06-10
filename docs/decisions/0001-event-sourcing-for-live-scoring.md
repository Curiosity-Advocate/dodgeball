# ADR-0001 — Event sourcing for live scoring

> **Context:** Expands overview.md §3. Driven by: `SCORE-*`, `RT-3`, `NFR-5`.

**Status:** Accepted. Adopted in v1.0.

---

## Context

Live scoring needs a record of a match that supports two things a plain
current-state store cannot: a client reconnecting mid-match must be able to catch
up without missing anything, and a scorekeeper must be able to correct a mistake
without destroying the history of what happened. The things users actually read —
the live score, the standings — are *views* over that record, not the record
itself.

## Decision

Model the write side as an **append-only event log** (`match_events`). Each scoring
action is an immutable event (`match_started`, `round_won_home`, `round_won_away`,
`score_correction`, `match_finalized`). The current score (`match_state`) and the
league table (`standings`) are **projections** folded from the log, and can be
rebuilt from it at any time. A correction is a new event, never an in-place update.

## Consequences

**Positive.**

- A complete, ordered history exists for free — the basis for reconnect by replay
  (`RT-3`, `NFR-5`).
- Corrections are non-destructive; the original events remain.
- Projections are disposable: if lost or changed, they are rebuilt from the log.

**Negative.**

- More conceptual weight than CRUD — contributors must understand the log /
  projection split.
- Projections must be kept consistent with the log and remain rebuildable.

## Alternatives considered

- **Current-state-only CRUD.** Storing just the live score discards history, so a
  reconnecting client cannot replay what it missed — which defeats the completeness
  guarantee that is the whole point of the system.
- **CRUD plus a bolt-on audit log.** Duplicates state across two places and invites
  drift between them; the log here *is* the state, avoiding that split.
