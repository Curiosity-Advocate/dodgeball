# ADR-0005 — Idempotency key on event append

> **Context:** Expands overview.md §6. Driven by: `SCORE-6`, `NFR-9`.

**Status:** Accepted. Adopted in v1.0.

---

## Context

The scorekeeper often works on an unreliable connection. A `POST` to append an
event can succeed on the server while the response is lost in transit; the client
cannot tell whether the action persisted. A naive retry then appends the event a
second time and the score double-counts — a round recorded twice.

## Decision

Require a **client-generated `idempotency_key` (UUID) per action**, created when the
user performs the action and reused unchanged on every retry of that same action.
`match_events` carries `UNIQUE (idempotency_key)`. On a duplicate key the server
returns the **original** event (`200`) and does not append again.

## Consequences

**Positive.**

- Retries after a lost response are safe — the action is applied exactly once.
- Simple and storage-light: the key lives on the event row itself, with no separate
  table or TTL to manage.
- Works regardless of writer count, so it remains correct when v2.0 adds multiple
  scorekeepers.

**Negative.**

- The client must generate the key **once per user action** and keep it stable
  across retries; regenerating per HTTP attempt would defeat it.

## Alternatives considered

- **Server-generated key.** The client cannot know a server-assigned id before a
  successful response, so it is useless for the retry case this protects.
- **Hash of the request content as the key.** Two legitimately identical actions
  (two `round_won_home` in a row) would collide and the second would be silently
  dropped.
- **Rely on the version check.** Cannot distinguish "my retry" from "a different new
  event", and in v1.0 there is no write-time version check at all (ADR-0004).
