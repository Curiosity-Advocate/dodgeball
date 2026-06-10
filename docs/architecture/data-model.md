# Data Model

This is the authoritative schema for v1.0. It expands [overview.md](../overview.md)
§5 into concrete PostgreSQL DDL with the rationale for the non-obvious choices.
The runnable migration (`schema.sql` / Alembic) is derived from this document in
the build phase; this page is the reference.

The model follows the data bands from overview §2: an append-only **event log** as
the source of truth, **projections** derived from it, **accounts** held to a higher
integrity bar, and plain **reference** entities.

## Conventions

- **Primary keys.** Sensitive entities use **UUID** keys to avoid enumeration:
  `users` and every foreign key pointing at it. All other entities use **BIGINT**
  identity keys, which are simpler and human-readable. UUIDs are generated with
  `gen_random_uuid()` (built into PostgreSQL 13+; older versions need the
  `pgcrypto` extension).
- **Timestamps** are `TIMESTAMPTZ`, always stored in UTC.
- **Event payloads** are `JSONB`, so event shapes can vary by type without schema
  churn.
- **Immutability.** Rows in the event log are never updated or deleted.

```sql
CREATE EXTENSION IF NOT EXISTS citext;   -- case-insensitive email
-- gen_random_uuid() is built-in on PostgreSQL 13+; otherwise:
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

## Accounts (slow / critical)

```sql
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         CITEXT UNIQUE NOT NULL,
    password_hash TEXT   NOT NULL,                      -- argon2id
    display_name  TEXT   NOT NULL,
    role          TEXT   NOT NULL DEFAULT 'scorekeeper'
                  CHECK (role IN ('scorekeeper', 'admin')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`users.id` is a UUID so account identifiers are not guessable. Viewers need no
account, so `role` is only `scorekeeper` or `admin`. `is_active` disables an
account without deleting its history.

```sql
CREATE TABLE refresh_tokens (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,                  -- sha256(opaque token)
    issued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    replaced_by BIGINT REFERENCES refresh_tokens(id),
    user_agent  TEXT
);
CREATE INDEX idx_refresh_user ON refresh_tokens(user_id);
```

Only the **hash** of a refresh token is stored. `replaced_by` forms the rotation
chain: a token presented after it has been replaced indicates reuse (theft) and is
grounds to revoke the chain.

## Reference & domain

```sql
CREATE TABLE competitions (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL,
    level      TEXT NOT NULL
               CHECK (level IN ('NATIONAL', 'STATE', 'INTERNATIONAL', 'LOCAL')),
    season     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE teams (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE matches (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    competition_id BIGINT NOT NULL REFERENCES competitions(id),
    home_team_id   BIGINT NOT NULL REFERENCES teams(id),
    away_team_id   BIGINT NOT NULL REFERENCES teams(id),
    scheduled_at   TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'scheduled'
                   CHECK (status IN ('scheduled', 'in_progress', 'final')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (home_team_id <> away_team_id)
);
CREATE INDEX idx_matches_competition ON matches(competition_id);
```

`matches.status` mirrors the lifecycle driven by events (`scheduled` →
`in_progress` → `final`); the `CHECK` forbids a team playing itself.

```sql
CREATE TABLE match_scorekeepers (
    match_id    BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    user_id     UUID   NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    assigned_by UUID   REFERENCES users(id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, user_id),
    UNIQUE (match_id)         -- v1.0: exactly one scorekeeper per match; drop in v2.0
);
```

The `UNIQUE (match_id)` constraint enforces the v1.0 rule of a single scorekeeper
per match at the database level. It is removed in v2.0 when multiple scorekeepers
are supported.

## Event log (append-only / immutable — the source of truth)

```sql
CREATE TABLE match_events (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- global order
    match_id        BIGINT NOT NULL REFERENCES matches(id),
    version         INT    NOT NULL,                  -- per-match cursor
    type            TEXT   NOT NULL CHECK (type IN (
                        'match_started',
                        'round_won_home',
                        'round_won_away',
                        'score_correction',
                        'match_finalized')),
    payload         JSONB  NOT NULL DEFAULT '{}'::jsonb,
    actor_id        UUID   NOT NULL REFERENCES users(id),
    idempotency_key UUID   NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (match_id, version),     -- per-match ordering; concurrency backstop (v2.0)
    UNIQUE (idempotency_key)        -- idempotent retries
);
CREATE INDEX idx_events_match_version ON match_events(match_id, version);
```

This is the heart of the model. `id` gives a global total order (a possible future
firehose feed); `version` is the **per-match** cursor used for ordered delivery and
replay. The two `UNIQUE` constraints carry most of the correctness:

- `UNIQUE (match_id, version)` guarantees a contiguous per-match sequence. In v1.0
  it is the structural backstop for ordering; in v2.0 it becomes the enforcement
  point for optimistic concurrency (ADR-0004).
- `UNIQUE (idempotency_key)` makes a retried append return the original event
  rather than duplicate it.

`actor_id` is a UUID FK to `users`. The replay index supports
`WHERE match_id = ? AND version > ?` directly.

## Projections (derived / recoverable)

```sql
CREATE TABLE match_state (
    match_id      BIGINT PRIMARY KEY REFERENCES matches(id) ON DELETE CASCADE,
    score_home    INT NOT NULL DEFAULT 0,
    score_away    INT NOT NULL DEFAULT 0,
    current_round INT NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'scheduled',
    version       INT NOT NULL DEFAULT 0,             -- last applied event version
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE standings (
    competition_id BIGINT NOT NULL REFERENCES competitions(id),
    team_id        BIGINT NOT NULL REFERENCES teams(id),
    played         INT NOT NULL DEFAULT 0,
    wins           INT NOT NULL DEFAULT 0,
    losses         INT NOT NULL DEFAULT 0,
    points         INT NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (competition_id, team_id)
);
```

`match_state` is the snapshot a new viewer reads; its `version` records the event
it is current as of, so a snapshot is self-describing (state + cursor). `standings`
is the simple within-competition points table, recomputed on finalisation. Because
both are derived, they carry no special durability requirement — if lost, they are
rebuilt by replaying `match_events` (`NFR-8`).

## Event payloads

| `type` | Payload | Effect on `match_state` |
|--------|---------|-------------------------|
| `match_started` | `{}` | `status` → `in_progress` |
| `round_won_home` | `{}` | `score_home += 1`, `current_round += 1` |
| `round_won_away` | `{}` | `score_away += 1`, `current_round += 1` |
| `score_correction` | `{ "score_home": N, "score_away": M }` | absolute scores set to N, M |
| `match_finalized` | `{}` | `status` → `final`; triggers `standings` recompute |

## Modelling notes

- **`version` semantics.** A per-match contiguous counter. In v1.0 it is purely the
  ordering/replay cursor; the write-time `expected_version` check is **not**
  enforced (a single scorekeeper plus the idempotency key suffices). In v2.0 the
  same column gains the optimistic-concurrency role for multiple writers (ADR-0004).
- **Access path.** All reads and writes to `match_events` go through the
  `EventStore` abstraction, never raw SQL at call sites, which keeps a future
  Postgres-outbox → Kafka move localised (ADR-0003).
- **Durability.** Only `match_events` and the account tables require high
  availability; projections are recomputable.
