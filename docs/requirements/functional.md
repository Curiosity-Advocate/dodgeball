# Functional Requirements

> **Scope:** v1.0 live-scoring MVP. Requirements are anchored on the **authorized
> scorekeeper** as the primary actor (see [overview.md](../overview.md) §1).
> Each requirement carries a stable prefixed ID; Architecture Decision Records
> cite these IDs as their drivers (e.g. *Driven by: `SCORE-6`*).

v1.0 assumes **exactly one scorekeeper per match**. Multiple scorekeepers per
match is deferred to v2.0 — see [Deferred to later versions](#deferred-to-later-versions).

---

## Identity & Access — `AUTH`

| ID | Requirement | Notes |
|----|-------------|-------|
| `AUTH‑1` | A user can register an account. | Email + password; password stored hashed. |
| `AUTH‑2` | A user can log in and receive an access token and a refresh token. | Access token is short-lived; refresh token is long-lived. |
| `AUTH‑3` | A user can exchange a valid refresh token for a new access token. | Refresh tokens rotate on use (old token is replaced). |
| `AUTH‑4` | A user can log out, revoking their refresh token. | Revoked tokens cannot be refreshed. |
| `AUTH‑5` | An admin can assign **a single** scorekeeper to a match, and unassign them. | Exactly one scorekeeper per match in v1.0. |
| `AUTH‑6` | The system enforces role-based access: **viewer**, **scorekeeper**, **admin**. | Viewing is open; writing requires scorekeeper assignment or admin. |

## Live Scoring — `SCORE`

| ID | Requirement | Notes |
|----|-------------|-------|
| `SCORE‑1` | An admin can create competitions, teams, and matches. | Match references a competition and two distinct teams. |
| `SCORE‑2` | The assigned scorekeeper can start a match. | Emits a `match_started` event; status → `in_progress`. |
| `SCORE‑3` | The assigned scorekeeper can record a round result (home or away). | Emits `round_won_home` / `round_won_away`; advances the score. |
| `SCORE‑4` | The assigned scorekeeper can issue a score correction. | Emits `score_correction` with the corrected absolute scores. |
| `SCORE‑5` | The assigned scorekeeper can finalize a match. | Emits `match_finalized`; status → `final`; triggers standings recompute (`RT-5`). |
| `SCORE‑6` | Event appends are idempotent. | Client supplies an idempotency key per action; a retry returns the original event, never a duplicate. |
| `SCORE‑7` | Every event is assigned a monotonic **per-match version** on append. | Provides the ordering/replay cursor for delivery (`RT-2`, `RT-3`). Retries are handled by the idempotency key (`SCORE-6`). Using `version` for write-time optimistic concurrency is **deferred to v2.0** (multiple scorekeepers). |

## Real-time Delivery — `RT`

| ID | Requirement | Notes |
|----|-------------|-------|
| `RT‑1` | A spectator can subscribe to a match's live feed over WebSocket. | Public for public matches; no account required to watch. |
| `RT‑2` | Each scoring event is pushed to subscribers in order. | Ordered by per-match version. |
| `RT‑3` | On reconnect, a client resumes from its last-seen version without missing updates. | Server replays events with version > last-seen (`READ-2`). |
| `RT‑4` | A snapshot of current state is available for fresh or unknown-gap clients. | Bounds reconnect cost: large/unknown gap → snapshot instead of replay. |
| `RT‑5` | Standings recompute when a match finalizes and the update is pushed to subscribers. | Simple within-competition points table. |

## Read & Query — `READ`

| ID | Requirement | Notes |
|----|-------------|-------|
| `READ‑1` | Anyone can fetch the current snapshot of a match. | Returns current state + the version it corresponds to. |
| `READ‑2` | Anyone can fetch a match's event history, or replay events since a given version. | Backs the reconnect flow (`RT-3`). |
| `READ‑3` | Anyone can fetch the standings for a competition. | |
| `READ‑4` | Anyone can list and filter matches. | By team, competition, date, and status. |

---

## Deferred to later versions

These are intentionally **out of v1.0 scope**; listed so the boundary is explicit.

| Item | Target |
|------|--------|
| Multiple scorekeepers per match — multi-writer coordination via `expected_version` (see ADR-0004) | v2.0 |
| Live game-state from video CV (round count, players-per-side) | v2.0 |
| Historical scraping of league platforms (Spawtz, PlayHQ) | Enrichment |
| Identity resolution / canonical entity deduplication | Enrichment |
| Cross-competition Elo / power rankings | Enrichment |
