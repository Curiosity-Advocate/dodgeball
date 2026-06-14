"""ReadService — public read queries over reference and projection tables.

Depends on core only; never touches the event log (snapshot and replay are served
in the api layer via the EventStore). Returns plain dicts shaped for the read API.
"""

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.read.errors import NotFound

_COMPETITION_COLUMNS = "id, name, level, season, created_at"
_TEAM_COLUMNS = "id, name, created_at"
_MATCH_COLUMNS = "id, competition_id, home_team_id, away_team_id, scheduled_at, status, created_at"


class ReadService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def match_exists(self, match_id: int) -> bool:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT 1 FROM matches WHERE id = :id"), {"id": match_id})
            ).one_or_none()
        return row is not None

    async def get_competition(self, competition_id: int) -> dict[str, Any]:
        return await self._one(
            f"SELECT {_COMPETITION_COLUMNS} FROM competitions WHERE id = :id",
            competition_id,
            "competition not found",
        )

    async def get_team(self, team_id: int) -> dict[str, Any]:
        return await self._one(
            f"SELECT {_TEAM_COLUMNS} FROM teams WHERE id = :id", team_id, "team not found"
        )

    async def get_match(self, match_id: int) -> dict[str, Any]:
        return await self._one(
            f"SELECT {_MATCH_COLUMNS} FROM matches WHERE id = :id", match_id, "match not found"
        )

    async def standings(self, competition_id: int) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM competitions WHERE id = :id"), {"id": competition_id}
                )
            ).one_or_none()
            if exists is None:
                raise NotFound("competition not found")
            rows = (
                await conn.execute(
                    text(
                        "SELECT competition_id, team_id, played, wins, losses, points, updated_at "
                        "FROM standings WHERE competition_id = :id ORDER BY points DESC, team_id"
                    ),
                    {"id": competition_id},
                )
            ).all()
        return [dict(r._mapping) for r in rows]

    async def list_matches(
        self,
        team: int | None = None,
        competition: int | None = None,
        match_date: date | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if team is not None:
            clauses.append("(home_team_id = :team OR away_team_id = :team)")
            params["team"] = team
        if competition is not None:
            clauses.append("competition_id = :competition")
            params["competition"] = competition
        if match_date is not None:
            clauses.append("scheduled_at::date = :match_date")
            params["match_date"] = match_date
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(f"SELECT {_MATCH_COLUMNS} FROM matches{where} ORDER BY id"), params
                )
            ).all()
        return [dict(r._mapping) for r in rows]

    async def _one(self, sql: str, entity_id: int, not_found: str) -> dict[str, Any]:
        async with self._engine.connect() as conn:
            row = (await conn.execute(text(sql), {"id": entity_id})).one_or_none()
        if row is None:
            raise NotFound(not_found)
        return dict(row._mapping)
