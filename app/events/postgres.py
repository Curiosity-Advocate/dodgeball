"""PostgresEventStore — the v1.0 EventStore implementation (ADR-0003).

The only module that reads or writes match_events directly. SQLAlchemy Core
(text) over an async engine; each method runs in its own transaction.
"""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.events import Event, EventType, MatchState, NewEvent
from app.core.projections import MatchResult, apply, compute_standings
from app.events.store import AppendResult, EventStore

# match_events columns whenever we materialise an Event, in dataclass field order.
_EVENT_COLUMNS = "id, match_id, version, type, payload, actor_id, idempotency_key, created_at"


def _row_to_event(row) -> Event:
    """Map a match_events row to the domain Event dataclass."""
    payload = row.payload
    if isinstance(payload, str):  # asyncpg may hand back jsonb as text
        payload = json.loads(payload)
    return Event(
        id=row.id,
        match_id=row.match_id,
        version=row.version,
        type=EventType(row.type),
        actor_id=str(row.actor_id),
        idempotency_key=str(row.idempotency_key),
        created_at=row.created_at,
        payload=payload,
    )


class PostgresEventStore(EventStore):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append(self, match_id: int, event: NewEvent) -> AppendResult:
        async with self._engine.begin() as conn:
            inserted = (
                await conn.execute(
                    text(f"""
                        INSERT INTO match_events
                            (match_id, version, type, payload, actor_id, idempotency_key)
                        SELECT :match_id,
                               COALESCE(MAX(version), 0) + 1,
                               :type, CAST(:payload AS jsonb),
                               CAST(:actor_id AS uuid), CAST(:idempotency_key AS uuid)
                        FROM match_events
                        WHERE match_id = :match_id
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING {_EVENT_COLUMNS}
                    """),
                    {
                        "match_id": match_id,
                        "type": event.type.value,
                        "payload": json.dumps(event.payload),
                        "actor_id": event.actor_id,
                        "idempotency_key": event.idempotency_key,
                    },
                )
            ).one_or_none()

            if inserted is None:
                # Duplicate idempotency_key: return the original, append nothing.
                original = (
                    await conn.execute(
                        text(
                            f"SELECT {_EVENT_COLUMNS} FROM match_events "
                            "WHERE idempotency_key = CAST(:k AS uuid)"
                        ),
                        {"k": event.idempotency_key},
                    )
                ).one()
                return AppendResult(_row_to_event(original), created=False)

            stored = _row_to_event(inserted)
            await self._write_through(conn, stored)
            if stored.type is EventType.MATCH_FINALIZED:
                await self._recompute_standings(conn, match_id)
            return AppendResult(stored, created=True)

    async def read_since(self, match_id: int, version: int) -> list[Event]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"SELECT {_EVENT_COLUMNS} FROM match_events "
                        "WHERE match_id = :m AND version > :v ORDER BY version"
                    ),
                    {"m": match_id, "v": version},
                )
            ).all()
        return [_row_to_event(r) for r in rows]

    async def snapshot(self, match_id: int) -> MatchState:
        async with self._engine.connect() as conn:
            return await self._read_state(conn, match_id)

    # ---- internal helpers ----

    async def _read_state(self, conn: AsyncConnection, match_id: int) -> MatchState:
        row = (
            await conn.execute(
                text(
                    "SELECT score_home, score_away, current_round, status, version "
                    "FROM match_state WHERE match_id = :m"
                ),
                {"m": match_id},
            )
        ).one_or_none()
        if row is None:
            return MatchState()
        return MatchState(
            score_home=row.score_home,
            score_away=row.score_away,
            current_round=row.current_round,
            status=row.status,
            version=row.version,
        )

    async def _write_through(self, conn: AsyncConnection, event: Event) -> None:
        """Apply the new event to the stored match_state row (upsert)."""
        new_state = apply(await self._read_state(conn, event.match_id), event)
        await conn.execute(
            text("""
                INSERT INTO match_state
                    (match_id, score_home, score_away, current_round, status, version, updated_at)
                VALUES (:match_id, :score_home, :score_away, :current_round,
                        :status, :version, now())
                ON CONFLICT (match_id) DO UPDATE SET
                    score_home = EXCLUDED.score_home,
                    score_away = EXCLUDED.score_away,
                    current_round = EXCLUDED.current_round,
                    status = EXCLUDED.status,
                    version = EXCLUDED.version,
                    updated_at = now()
            """),
            {
                "match_id": event.match_id,
                "score_home": new_state.score_home,
                "score_away": new_state.score_away,
                "current_round": new_state.current_round,
                "status": new_state.status,
                "version": new_state.version,
            },
        )
        # Mirror the lifecycle status onto the matches row so list/filter queries
        # see the live status; only the two transitions change it.
        if event.type in (EventType.MATCH_STARTED, EventType.MATCH_FINALIZED):
            await conn.execute(
                text("UPDATE matches SET status = :s WHERE id = :m"),
                {"s": new_state.status, "m": event.match_id},
            )

    async def _recompute_standings(self, conn: AsyncConnection, match_id: int) -> None:
        """Full recompute of the competition's standings from its finalised
        matches, in the same transaction as the finalising event.
        """
        competition_id = (
            await conn.execute(
                text("SELECT competition_id FROM matches WHERE id = :m"),
                {"m": match_id},
            )
        ).scalar_one()

        rows = (
            await conn.execute(
                text("""
                    SELECT m.home_team_id, m.away_team_id, s.score_home, s.score_away
                    FROM matches m
                    JOIN match_state s ON s.match_id = m.id
                    WHERE m.competition_id = :c AND s.status = 'final'
                """),
                {"c": competition_id},
            )
        ).all()
        results = [
            MatchResult(r.home_team_id, r.away_team_id, r.score_home, r.score_away) for r in rows
        ]

        standings = compute_standings(competition_id, results)

        await conn.execute(
            text("DELETE FROM standings WHERE competition_id = :c"),
            {"c": competition_id},
        )
        for st in standings:
            await conn.execute(
                text("""
                    INSERT INTO standings
                        (competition_id, team_id, played, wins, losses, points, updated_at)
                    VALUES (:competition_id, :team_id, :played, :wins, :losses,
                            :points, now())
                """),
                {
                    "competition_id": st.competition_id,
                    "team_id": st.team_id,
                    "played": st.played,
                    "wins": st.wins,
                    "losses": st.losses,
                    "points": st.points,
                },
            )
