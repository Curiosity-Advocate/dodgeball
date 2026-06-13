"""Integration tests — verify schema constraints against a real Postgres.

These tests are skipped automatically when DATABASE_URL is not set or the
database is unreachable, so the suite stays green on machines without Postgres
(e.g. CI before the DB service is wired up).

The CI pipeline runs these after:
    uv run alembic upgrade head
    uv run python -m app.seed   (twice, to prove idempotency)
"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL not set — skipping integration tests",
)


@pytest.fixture
async def conn():
    """Yield an async connection whose transaction is always rolled back."""
    if not DATABASE_URL:
        pytest.skip("no database")
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            trans = await connection.begin()
            try:
                yield connection
            finally:
                await trans.rollback()
    except OperationalError:
        pytest.skip("database not reachable")
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_user(conn, email: str, role: str = "scorekeeper") -> str:
    result = await conn.execute(
        text("""
            INSERT INTO users (email, password_hash, display_name, role)
            VALUES (:email, 'hash', 'Test User', :role)
            RETURNING id
        """),
        {"email": email, "role": role},
    )
    return str(result.scalar_one())


async def _insert_competition(conn) -> int:
    result = await conn.execute(
        text(
            "INSERT INTO competitions (name, level) VALUES ('Test League', 'NATIONAL') RETURNING id"
        ),
    )
    return result.scalar_one()


async def _insert_team(conn, name: str) -> int:
    result = await conn.execute(
        text("INSERT INTO teams (name) VALUES (:name) RETURNING id"),
        {"name": name},
    )
    return result.scalar_one()


async def _insert_match(conn, comp_id: int, home_id: int, away_id: int) -> int:
    result = await conn.execute(
        text("""
            INSERT INTO matches (competition_id, home_team_id, away_team_id)
            VALUES (:comp, :home, :away)
            RETURNING id
        """),
        {"comp": comp_id, "home": home_id, "away": away_id},
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Constraint tests
# ---------------------------------------------------------------------------


async def test_email_unique_is_case_insensitive(conn):
    """citext makes email unique regardless of case."""
    await _insert_user(conn, "Alice@example.com")
    with pytest.raises(IntegrityError):
        await _insert_user(conn, "alice@EXAMPLE.com")


async def test_team_vs_itself_rejected(conn):
    """matches.CHECK ensures home_team_id <> away_team_id."""
    comp_id = await _insert_competition(conn)
    team_id = await _insert_team(conn, "Solo Team")
    with pytest.raises(IntegrityError):
        await _insert_match(conn, comp_id, team_id, team_id)


async def test_one_scorekeeper_per_match(conn):
    """UNIQUE (match_id) on match_scorekeepers enforces v1.0 single-scorekeeper rule."""
    comp_id = await _insert_competition(conn)
    home_id = await _insert_team(conn, "Home Team SC")
    away_id = await _insert_team(conn, "Away Team SC")
    match_id = await _insert_match(conn, comp_id, home_id, away_id)
    user1 = await _insert_user(conn, "keeper1@test.local")
    user2 = await _insert_user(conn, "keeper2@test.local")

    await conn.execute(
        text("INSERT INTO match_scorekeepers (match_id, user_id) VALUES (:m, :u)"),
        {"m": match_id, "u": user1},
    )
    with pytest.raises(IntegrityError):
        await conn.execute(
            text("INSERT INTO match_scorekeepers (match_id, user_id) VALUES (:m, :u)"),
            {"m": match_id, "u": user2},
        )


async def test_match_event_version_unique(conn):
    """UNIQUE (match_id, version) prevents two events with the same per-match version."""
    comp_id = await _insert_competition(conn)
    home_id = await _insert_team(conn, "Home EV")
    away_id = await _insert_team(conn, "Away EV")
    match_id = await _insert_match(conn, comp_id, home_id, away_id)
    actor_id = await _insert_user(conn, "actor@test.local")

    idem1 = str(uuid.uuid4())
    idem2 = str(uuid.uuid4())

    await conn.execute(
        text("""
            INSERT INTO match_events (match_id, version, type, actor_id, idempotency_key)
            VALUES (:m, 1, 'match_started', :a, :k)
        """),
        {"m": match_id, "a": actor_id, "k": idem1},
    )
    with pytest.raises(IntegrityError):
        await conn.execute(
            text("""
                INSERT INTO match_events (match_id, version, type, actor_id, idempotency_key)
                VALUES (:m, 1, 'round_won_home', :a, :k)
            """),
            {"m": match_id, "a": actor_id, "k": idem2},
        )


async def test_idempotency_key_unique(conn):
    """UNIQUE (idempotency_key) prevents the same client action being applied twice."""
    comp_id = await _insert_competition(conn)
    home_id = await _insert_team(conn, "Home IK")
    away_id = await _insert_team(conn, "Away IK")
    match_id = await _insert_match(conn, comp_id, home_id, away_id)
    actor_id = await _insert_user(conn, "ik-actor@test.local")

    shared_key = str(uuid.uuid4())

    await conn.execute(
        text("""
            INSERT INTO match_events (match_id, version, type, actor_id, idempotency_key)
            VALUES (:m, 1, 'match_started', :a, :k)
        """),
        {"m": match_id, "a": actor_id, "k": shared_key},
    )
    with pytest.raises(IntegrityError):
        await conn.execute(
            text("""
                INSERT INTO match_events (match_id, version, type, actor_id, idempotency_key)
                VALUES (:m, 2, 'round_won_home', :a, :k)
            """),
            {"m": match_id, "a": actor_id, "k": shared_key},
        )


async def test_invalid_role_rejected(conn):
    """users.role CHECK rejects anything outside (scorekeeper, admin)."""
    with pytest.raises(IntegrityError):
        await conn.execute(
            text("""
                INSERT INTO users (email, password_hash, display_name, role)
                VALUES ('bad@test.local', 'hash', 'Bad User', 'superuser')
            """),
        )


async def test_invalid_event_type_rejected(conn):
    """match_events.type CHECK rejects unknown event types."""
    comp_id = await _insert_competition(conn)
    home_id = await _insert_team(conn, "Home ET")
    away_id = await _insert_team(conn, "Away ET")
    match_id = await _insert_match(conn, comp_id, home_id, away_id)
    actor_id = await _insert_user(conn, "et-actor@test.local")

    with pytest.raises(IntegrityError):
        await conn.execute(
            text("""
                INSERT INTO match_events (match_id, version, type, actor_id, idempotency_key)
                VALUES (:m, 1, 'goal_scored', :a, :k)
            """),
            {"m": match_id, "a": actor_id, "k": str(uuid.uuid4())},
        )


async def test_invalid_competition_level_rejected(conn):
    """competitions.level CHECK rejects unknown levels."""
    with pytest.raises(IntegrityError):
        await conn.execute(
            text("""
                INSERT INTO competitions (name, level)
                VALUES ('Bad League', 'GLOBAL')
            """),
        )


async def test_seed_data_present(conn):
    """After running the seed script the demo user and entities exist."""
    row = await conn.execute(
        text("SELECT COUNT(*) FROM users WHERE email = 'scorekeeper@demo.local'"),
    )
    assert row.scalar_one() == 1, (
        "Demo scorekeeper not found — did you run `uv run python -m app.seed`?"
    )

    row = await conn.execute(
        text("SELECT COUNT(*) FROM competitions WHERE name = 'Demo National League'"),
    )
    assert row.scalar_one() == 1

    row = await conn.execute(
        text("SELECT COUNT(*) FROM teams WHERE name IN ('Demo Hawks', 'Demo Owls')"),
    )
    assert row.scalar_one() == 2
