"""Seed demo data for local development.

Creates one competition, two teams, one match, and one scorekeeper account.
Idempotent: each entity is looked up first and only inserted if absent, so
running this script multiple times is always safe.

Usage:
    uv run python -m app.seed
"""

import asyncio

from argon2 import PasswordHasher
from sqlalchemy import text

from app.core.db import get_engine

DEMO_EMAIL = "scorekeeper@demo.local"
DEMO_PASSWORD = "demo-password"  # noqa: S105 — demo data only, never used in production


async def seed() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        user_id = await _get_or_create_user(conn)
        comp_id = await _get_or_create_competition(conn)
        home_id = await _get_or_create_team(conn, "Demo Hawks")
        away_id = await _get_or_create_team(conn, "Demo Owls")
        match_id = await _get_or_create_match(conn, comp_id, home_id, away_id)
        await _get_or_create_scorekeeper(conn, match_id, user_id)
    await engine.dispose()
    print("Seed complete.")  # noqa: T201


async def _get_or_create_user(conn) -> str:
    row = await conn.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": DEMO_EMAIL},
    )
    existing = row.scalar_one_or_none()
    if existing is not None:
        return str(existing)

    ph = PasswordHasher()
    hashed = ph.hash(DEMO_PASSWORD)
    result = await conn.execute(
        text("""
            INSERT INTO users (email, password_hash, display_name, role)
            VALUES (:email, :hash, 'Demo Scorekeeper', 'scorekeeper')
            RETURNING id
        """),
        {"email": DEMO_EMAIL, "hash": hashed},
    )
    return str(result.scalar_one())


async def _get_or_create_competition(conn) -> int:
    row = await conn.execute(
        text("SELECT id FROM competitions WHERE name = :name"),
        {"name": "Demo National League"},
    )
    existing = row.scalar_one_or_none()
    if existing is not None:
        return existing

    result = await conn.execute(
        text("""
            INSERT INTO competitions (name, level, season)
            VALUES ('Demo National League', 'NATIONAL', '2026')
            RETURNING id
        """),
    )
    return result.scalar_one()


async def _get_or_create_team(conn, name: str) -> int:
    row = await conn.execute(
        text("SELECT id FROM teams WHERE name = :name"),
        {"name": name},
    )
    existing = row.scalar_one_or_none()
    if existing is not None:
        return existing

    result = await conn.execute(
        text("INSERT INTO teams (name) VALUES (:name) RETURNING id"),
        {"name": name},
    )
    return result.scalar_one()


async def _get_or_create_match(conn, comp_id: int, home_id: int, away_id: int) -> int:
    row = await conn.execute(
        text("""
            SELECT id FROM matches
            WHERE competition_id = :comp AND home_team_id = :home AND away_team_id = :away
        """),
        {"comp": comp_id, "home": home_id, "away": away_id},
    )
    existing = row.scalar_one_or_none()
    if existing is not None:
        return existing

    result = await conn.execute(
        text("""
            INSERT INTO matches (competition_id, home_team_id, away_team_id)
            VALUES (:comp, :home, :away)
            RETURNING id
        """),
        {"comp": comp_id, "home": home_id, "away": away_id},
    )
    match_id = result.scalar_one()

    # Initialise the match_state projection row
    await conn.execute(
        text("INSERT INTO match_state (match_id) VALUES (:mid)"),
        {"mid": match_id},
    )
    return match_id


async def _get_or_create_scorekeeper(conn, match_id: int, user_id: str) -> None:
    await conn.execute(
        text("""
            INSERT INTO match_scorekeepers (match_id, user_id)
            VALUES (:match_id, :user_id)
            ON CONFLICT DO NOTHING
        """),
        {"match_id": match_id, "user_id": user_id},
    )


if __name__ == "__main__":
    asyncio.run(seed())
