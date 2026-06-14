"""Shared test fixtures.

DB-backed tests get total isolation via TRUNCATE: every test that requests the
`engine` fixture starts from an empty set of domain tables (testing-strategy.md).
This replaces the old per-file marker-prefix DELETE cleanup. Pure unit tests
request no DB fixture and never touch Postgres.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Every domain table. CASCADE handles FK order; alembic_version is left alone.
# RESTART IDENTITY resets the BIGINT sequences so IDs are predictable per test.
_DOMAIN_TABLES = (
    "match_events",
    "match_state",
    "standings",
    "match_scorekeepers",
    "refresh_tokens",
    "matches",
    "teams",
    "competitions",
    "users",
)


async def truncate_all(engine: AsyncEngine) -> None:
    """Wipe every domain table so the next test starts from empty."""
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_DOMAIN_TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def engine():
    """A real-Postgres engine for one test, with the DB truncated on entry.

    Skips (rather than fails) when DATABASE_URL is unset or the database is
    unreachable, so the suite stays green on machines without Postgres.
    """
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    eng = create_async_engine(DATABASE_URL)
    try:
        await truncate_all(eng)
    except OperationalError:
        await eng.dispose()
        pytest.skip("database not reachable")
    try:
        yield eng
    finally:
        await eng.dispose()
