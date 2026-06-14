"""ManagementService — admin CRUD of reference entities (competitions, teams, matches).

Holds the engine and runs each method in its own transaction with Core text().
Owns the competitions, teams, and matches tables.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.management.errors import InvalidReference


@dataclass(frozen=True)
class Competition:
    id: int
    name: str
    level: str
    season: str | None
    created_at: datetime


@dataclass(frozen=True)
class Team:
    id: int
    name: str
    created_at: datetime


@dataclass(frozen=True)
class Match:
    id: int
    competition_id: int
    home_team_id: int
    away_team_id: int
    scheduled_at: datetime | None
    status: str
    created_at: datetime


class ManagementService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create_competition(
        self, name: str, level: str, season: str | None = None
    ) -> Competition:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "INSERT INTO competitions (name, level, season) "
                        "VALUES (:name, :level, :season) "
                        "RETURNING id, name, level, season, created_at"
                    ),
                    {"name": name, "level": level, "season": season},
                )
            ).one()
        return Competition(row.id, row.name, row.level, row.season, row.created_at)

    async def create_team(self, name: str) -> Team:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text("INSERT INTO teams (name) VALUES (:name) RETURNING id, name, created_at"),
                    {"name": name},
                )
            ).one()
        return Team(row.id, row.name, row.created_at)

    async def create_match(
        self,
        competition_id: int,
        home_team_id: int,
        away_team_id: int,
        scheduled_at: datetime | None = None,
    ) -> Match:
        try:
            async with self._engine.begin() as conn:
                row = (
                    await conn.execute(
                        text(
                            "INSERT INTO matches "
                            "(competition_id, home_team_id, away_team_id, scheduled_at) "
                            "VALUES (:c, :h, :a, :s) "
                            "RETURNING id, competition_id, home_team_id, away_team_id, "
                            "scheduled_at, status, created_at"
                        ),
                        {
                            "c": competition_id,
                            "h": home_team_id,
                            "a": away_team_id,
                            "s": scheduled_at,
                        },
                    )
                ).one()
        except IntegrityError as exc:
            # bad competition_id / team_id FK (the home != away CHECK is enforced
            # earlier by the request schema).
            raise InvalidReference("competition or team does not exist") from exc
        return Match(
            row.id,
            row.competition_id,
            row.home_team_id,
            row.away_team_id,
            row.scheduled_at,
            row.status,
            row.created_at,
        )

    async def match_exists(self, match_id: int) -> bool:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT 1 FROM matches WHERE id = :id"), {"id": match_id}
                )
            ).one_or_none()
        return row is not None
