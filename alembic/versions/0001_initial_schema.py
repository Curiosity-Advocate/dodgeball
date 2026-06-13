"""Initial schema — all tables, constraints, and indexes.

Raw SQL verbatim from docs/architecture/data-model.md, applied in
foreign-key dependency order.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- extension ---------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # -- accounts ----------------------------------------------------------
    op.execute("""
        CREATE TABLE users (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email         CITEXT UNIQUE NOT NULL,
            password_hash TEXT   NOT NULL,
            display_name  TEXT   NOT NULL,
            role          TEXT   NOT NULL DEFAULT 'scorekeeper'
                          CHECK (role IN ('scorekeeper', 'admin')),
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE refresh_tokens (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash  TEXT NOT NULL UNIQUE,
            issued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at  TIMESTAMPTZ NOT NULL,
            revoked_at  TIMESTAMPTZ,
            replaced_by BIGINT REFERENCES refresh_tokens(id),
            user_agent  TEXT
        )
    """)
    op.execute("CREATE INDEX idx_refresh_user ON refresh_tokens(user_id)")

    # -- reference / domain ------------------------------------------------
    op.execute("""
        CREATE TABLE competitions (
            id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name       TEXT NOT NULL,
            level      TEXT NOT NULL
                       CHECK (level IN ('NATIONAL', 'STATE', 'INTERNATIONAL', 'LOCAL')),
            season     TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE teams (
            id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
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
        )
    """)
    op.execute("CREATE INDEX idx_matches_competition ON matches(competition_id)")

    op.execute("""
        CREATE TABLE match_scorekeepers (
            match_id    BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
            user_id     UUID   NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
            assigned_by UUID   REFERENCES users(id),
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (match_id, user_id),
            UNIQUE (match_id)
        )
    """)

    # -- event log (append-only / immutable) --------------------------------
    op.execute("""
        CREATE TABLE match_events (
            id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            match_id        BIGINT NOT NULL REFERENCES matches(id),
            version         INT    NOT NULL,
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
            UNIQUE (match_id, version),
            UNIQUE (idempotency_key)
        )
    """)
    op.execute("CREATE INDEX idx_events_match_version ON match_events(match_id, version)")

    # -- projections (derived / recoverable) --------------------------------
    op.execute("""
        CREATE TABLE match_state (
            match_id      BIGINT PRIMARY KEY REFERENCES matches(id) ON DELETE CASCADE,
            score_home    INT NOT NULL DEFAULT 0,
            score_away    INT NOT NULL DEFAULT 0,
            current_round INT NOT NULL DEFAULT 0,
            status        TEXT NOT NULL DEFAULT 'scheduled',
            version       INT NOT NULL DEFAULT 0,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE standings (
            competition_id BIGINT NOT NULL REFERENCES competitions(id),
            team_id        BIGINT NOT NULL REFERENCES teams(id),
            played         INT NOT NULL DEFAULT 0,
            wins           INT NOT NULL DEFAULT 0,
            losses         INT NOT NULL DEFAULT 0,
            points         INT NOT NULL DEFAULT 0,
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (competition_id, team_id)
        )
    """)


def downgrade() -> None:
    # Reverse dependency order
    op.execute("DROP TABLE IF EXISTS standings")
    op.execute("DROP TABLE IF EXISTS match_state")
    op.execute("DROP INDEX  IF EXISTS idx_events_match_version")
    op.execute("DROP TABLE IF EXISTS match_events")
    op.execute("DROP TABLE IF EXISTS match_scorekeepers")
    op.execute("DROP INDEX  IF EXISTS idx_matches_competition")
    op.execute("DROP TABLE IF EXISTS matches")
    op.execute("DROP TABLE IF EXISTS teams")
    op.execute("DROP TABLE IF EXISTS competitions")
    op.execute("DROP INDEX  IF EXISTS idx_refresh_user")
    op.execute("DROP TABLE IF EXISTS refresh_tokens")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP EXTENSION IF EXISTS citext")