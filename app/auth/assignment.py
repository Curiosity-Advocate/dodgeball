"""Scorekeeper assignment + per-match authorisation (ADR-0008).

Owns match_scorekeepers. v1.0: exactly one scorekeeper per match
(UNIQUE(match_id)), so assign replaces any existing assignment. get_scorekeeper
backs the per-match write authorisation check.
"""

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.errors import InvalidAssignment


class AssignmentService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def assign(self, match_id: int, user_id: str, assigned_by: str) -> None:
        """Set the single scorekeeper for a match, replacing any existing one."""
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM match_scorekeepers WHERE match_id = :m"),
                    {"m": match_id},
                )
                await conn.execute(
                    text(
                        "INSERT INTO match_scorekeepers (match_id, user_id, assigned_by) "
                        "VALUES (:m, CAST(:u AS uuid), CAST(:by AS uuid))"
                    ),
                    {"m": match_id, "u": user_id, "by": assigned_by},
                )
        except IntegrityError as exc:
            raise InvalidAssignment("user does not exist") from exc

    async def unassign(self, match_id: int) -> None:
        """Remove the match's scorekeeper assignment (no-op if none)."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM match_scorekeepers WHERE match_id = :m"),
                {"m": match_id},
            )

    async def get_scorekeeper(self, match_id: int) -> str | None:
        """The match's assigned scorekeeper user_id, or None — used by authz."""
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT user_id FROM match_scorekeepers WHERE match_id = :m"),
                    {"m": match_id},
                )
            ).one_or_none()
        return str(row.user_id) if row else None
