# API Contract

The authoritative interface for v1.0, expanding [overview.md](../overview.md) §6.
Three surfaces: an authenticated write path (scoring), a public read path, and a
WebSocket live path.

## Conventions

- JSON over HTTPS. Timestamps are UTC ISO-8601.
- Writes require `Authorization: Bearer <access_token>`. Reads are public unless
  noted.
- Errors use a single envelope:

  ```json
  { "error": { "code": "version_conflict", "message": "human-readable detail" } }
  ```

- IDs: `users` are UUIDs; competitions/teams/matches are integers.

## Auth

| Method | Path | Auth | Body | Success |
|--------|------|------|------|---------|
| POST | `/auth/register` | public | `{ email, password, display_name }` | `201 { user }` |
| POST | `/auth/login` | public | `{ email, password }` | `200 { access_token, refresh_token, token_type, expires_in }` |
| POST | `/auth/refresh` | public | `{ refresh_token }` | `200 { access_token, refresh_token, ... }` (rotated) |
| POST | `/auth/logout` | public | `{ refresh_token }` | `204` |
| GET | `/auth/me` | bearer | — | `200 { user }` |

`login` and `refresh` return a new refresh token each time (rotation). `refresh`
rejects a token that is expired, revoked, or already replaced. `register` returns
`409` if the email is already registered.

## Management (admin)

| Method | Path | Body |
|--------|------|------|
| POST | `/competitions` | `{ name, level, season }` |
| POST | `/teams` | `{ name }` |
| POST | `/matches` | `{ competition_id, home_team_id, away_team_id, scheduled_at }` |
| PUT | `/matches/{id}/scorekeeper` | `{ user_id }` — sets the single scorekeeper |
| DELETE | `/matches/{id}/scorekeeper` | — unassign |

## Scoring (write)

### `POST /matches/{id}/events`

Auth: the assigned scorekeeper for this match, or an admin.

**v1.0 request:**

```json
{
  "type": "round_won_home",
  "payload": {},
  "idempotency_key": "b3f1c2a4-9e7d-4c1a-8f55-2a1d0c9e7b10"
}
```

`type` ∈ `match_started | round_won_home | round_won_away | score_correction | match_finalised`.
For `score_correction`, `payload` is `{ "score_home": N, "score_away": M }`.
The `idempotency_key` is a client-generated UUID, stable across retries of the same
action.

**Response:**

```json
{
  "event": { "id": 1024, "version": 8, "type": "round_won_home",
             "payload": {}, "created_at": "2026-06-10T04:21:00Z" },
  "state": { "score_home": 4, "score_away": 2, "current_round": 6,
             "status": "in_progress", "version": 8 }
}
```

| Status | When |
|--------|------|
| `201` | event appended |
| `200` | duplicate `idempotency_key` — the original event is returned (no second append) |
| `403` | caller is not the assigned scorekeeper / admin |
| `404` | match not found |
| `422` | invalid `type` or `payload` |

> **v2.0 addition.** With multiple scorekeepers, the request gains an
> `expected_version` field and the response may be `409` (`version_conflict`,
> returning `current_version`) when a write is stale; the client refetches and
> retries. This optimistic-concurrency behaviour is **not** part of the v1.0
> contract (ADR-0004).

## Read (public)

### `GET /matches/{id}/snapshot`

```json
{ "match_id": 12, "score_home": 4, "score_away": 2,
  "current_round": 6, "status": "in_progress", "version": 8 }
```

### `GET /matches/{id}/events?since={version}`

Replay for reconnect — events with `version` greater than `since`, in order.

```json
{ "events": [
    { "version": 7, "type": "round_won_away", "payload": {}, "created_at": "..." },
    { "version": 8, "type": "round_won_home", "payload": {}, "created_at": "..." }
] }
```

### Other reads

| Method | Path | Notes |
|--------|------|-------|
| GET | `/competitions/{id}/standings` | points table |
| GET | `/matches?team=&competition=&date=&status=` | list / filter; each item carries team & competition **names** and the live **score** (so a client can render a readable game list in one request) |
| GET | `/matches/{id}`, `/teams/{id}`, `/competitions/{id}` | entity detail |

A `/matches` list item:

```json
{
  "id": 1, "competition_id": 1, "home_team_id": 1, "away_team_id": 2,
  "scheduled_at": null, "status": "in_progress", "created_at": "…",
  "home_team_name": "Demo Hawks", "away_team_name": "Demo Owls",
  "competition_name": "Demo National League",
  "score_home": 2, "score_away": 1
}
```

## WebSocket (live)

### `WS /matches/{id}`

Public for public matches. The client tracks the `version` it has applied.

**Server → client** (one message per appended event):

```json
{
  "version": 8,
  "type": "round_won_home",
  "payload": {},
  "state": { "score_home": 4, "score_away": 2, "current_round": 6, "status": "in_progress" }
}
```

**Reconnect protocol:**

1. On (re)connect the client sends `{ "last_version": 6 }`.
2. The server replays events with `version > 6`, then resumes the live stream.
3. For an unknown or very large gap, the client instead calls
   `GET /matches/{id}/snapshot`, adopts that state and `version`, and continues.

**Client ordering rules:**

- Apply events strictly in ascending `version`.
- Buffer out-of-order arrivals; on a `version` gap, request replay via
  `GET /matches/{id}/events?since=<last_applied>` before continuing.
- Ignore any `version` ≤ the last applied (dedupe).

## Status-code summary

| Code | Meaning here |
|------|--------------|
| `200` | OK / idempotent replay |
| `201` | created (event appended, entity created) |
| `204` | success, no body (logout, unassign) |
| `401` | missing / invalid access token |
| `403` | authenticated but not authorised (not assigned / not admin) |
| `404` | not found |
| `409` | conflict — duplicate email on `register`; also v2.0 version conflict in scoring (optimistic concurrency) |
| `422` | validation error |
| `429` | rate-limited (auth endpoints) |
