# ADR-0008 — Per-match authorisation outside the token

> **Context:** Expands overview.md §6. Driven by: `AUTH-5`, `AUTH-6`, `NFR-13`.

**Status:** Accepted. Adopted in v1.0.

---

## Context

Writing to a match requires the caller to be that match's assigned scorekeeper, or
an admin (`NFR-13`). The access token (ADR-0007) carries the user's role, but
per-match assignments are mutable — an admin can assign or unassign a scorekeeper at
any time, including during the life of an already-issued token.

## Decision

Keep **per-match authorisation out of the token**. The JWT carries only identity and
role. On each write, the server checks the caller against the **current**
`match_scorekeepers` assignment for that match. Role alone is never sufficient for a
write; the assignment is the deciding fact and is read at request time.

## Consequences

**Positive.**

- Assignment changes take effect immediately — unassigning a scorekeeper revokes
  their write access at once, with no wait for a token to expire.
- Tokens stay small and stable; they need not be reissued when assignments change.
- The `match_scorekeepers` table is the single source of truth for who may write.

**Negative.**

- A lookup per write to resolve the assignment — cheap, and cacheable (e.g. in
  Redis) if it ever matters.

## Alternatives considered

- **Encode assignments in the JWT.** They would go stale the moment an assignment
  changed, bloat the token, and could not be revoked until expiry.
- **A separate per-match write token.** More moving parts for no benefit over a
  request-time assignment check.
