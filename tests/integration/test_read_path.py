"""Contract tests for the public read path against real Postgres."""

import uuid
from dataclasses import dataclass

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from app.api.deps import get_event_store, get_read_service
from app.api.main import create_app
from app.core.events import EventType, NewEvent
from app.events.postgres import PostgresEventStore
from app.read.service import ReadService


@dataclass
class Ctx:
    client: httpx.AsyncClient
    engine: object
    actor_id: str
    competition_id: int
    home_id: int
    away_id: int
    match_id: int


@pytest.fixture
async def ctx(engine):
    async with engine.begin() as conn:
        comp = (
            await conn.execute(
                text(
                    "INSERT INTO competitions (name, level) "
                    "VALUES ('RDTEST League', 'NATIONAL') RETURNING id"
                )
            )
        ).scalar_one()
        home = (
            await conn.execute(text("INSERT INTO teams (name) VALUES ('RDTEST Home') RETURNING id"))
        ).scalar_one()
        away = (
            await conn.execute(text("INSERT INTO teams (name) VALUES ('RDTEST Away') RETURNING id"))
        ).scalar_one()
        match = (
            await conn.execute(
                text(
                    "INSERT INTO matches (competition_id, home_team_id, away_team_id) "
                    "VALUES (:c, :h, :a) RETURNING id"
                ),
                {"c": comp, "h": home, "a": away},
            )
        ).scalar_one()
        actor = (
            await conn.execute(
                text(
                    "INSERT INTO users (email, password_hash, display_name) "
                    "VALUES (:e, 'x', 'RD') RETURNING id"
                ),
                {"e": f"{uuid.uuid4()}@rdtest.local"},
            )
        ).scalar_one()

    actor_id = str(actor)
    store = PostgresEventStore(engine)

    def ev(type_: EventType, payload: dict | None = None) -> NewEvent:
        return NewEvent(
            type=type_, actor_id=actor_id, idempotency_key=str(uuid.uuid4()), payload=payload or {}
        )

    await store.append(match, ev(EventType.MATCH_STARTED))
    await store.append(match, ev(EventType.ROUND_WON_HOME))
    await store.append(match, ev(EventType.ROUND_WON_HOME))

    app = create_app()
    app.dependency_overrides[get_read_service] = lambda: ReadService(engine)
    app.dependency_overrides[get_event_store] = lambda: PostgresEventStore(engine)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Ctx(client, engine, actor_id, comp, home, away, match)
    app.dependency_overrides.clear()


async def test_snapshot_returns_state_and_version(ctx):
    r = await ctx.client.get(f"/matches/{ctx.match_id}/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["match_id"] == ctx.match_id
    assert (body["score_home"], body["score_away"]) == (2, 0)
    assert body["status"] == "in_progress"
    assert body["version"] == 3


async def test_snapshot_unknown_match_404(ctx):
    assert (await ctx.client.get("/matches/999999/snapshot")).status_code == 404


async def test_replay_since(ctx):
    r = await ctx.client.get(f"/matches/{ctx.match_id}/events", params={"since": 1})
    assert r.status_code == 200
    assert [e["version"] for e in r.json()["events"]] == [2, 3]


async def test_replay_full_log_by_default(ctx):
    r = await ctx.client.get(f"/matches/{ctx.match_id}/events")
    assert [e["version"] for e in r.json()["events"]] == [1, 2, 3]


async def test_replay_unknown_match_404(ctx):
    assert (await ctx.client.get("/matches/999999/events")).status_code == 404


async def test_standings_after_finalise(ctx):
    store = PostgresEventStore(ctx.engine)
    await store.append(
        ctx.match_id,
        NewEvent(
            type=EventType.MATCH_FINALISED,
            actor_id=ctx.actor_id,
            idempotency_key=str(uuid.uuid4()),
            payload={},
        ),
    )
    r = await ctx.client.get(f"/competitions/{ctx.competition_id}/standings")
    assert r.status_code == 200
    table = {row["team_id"]: row for row in r.json()["standings"]}
    assert table[ctx.home_id]["points"] == 3
    assert table[ctx.away_id]["points"] == 0


async def test_standings_unknown_competition_404(ctx):
    assert (await ctx.client.get("/competitions/999999/standings")).status_code == 404


async def test_list_matches_by_competition(ctx):
    r = await ctx.client.get("/matches", params={"competition": ctx.competition_id})
    assert r.status_code == 200
    assert ctx.match_id in [m["id"] for m in r.json()["matches"]]


async def test_list_matches_by_status_in_progress(ctx):
    r = await ctx.client.get("/matches", params={"status": "in_progress"})
    assert ctx.match_id in [m["id"] for m in r.json()["matches"]]


async def test_get_match_detail(ctx):
    r = await ctx.client.get(f"/matches/{ctx.match_id}")
    assert r.status_code == 200
    assert r.json()["id"] == ctx.match_id


async def test_get_match_unknown_404(ctx):
    assert (await ctx.client.get("/matches/999999")).status_code == 404


async def test_get_team_detail_and_404(ctx):
    assert (await ctx.client.get(f"/teams/{ctx.home_id}")).json()["name"] == "RDTEST Home"
    assert (await ctx.client.get("/teams/999999")).status_code == 404


async def test_get_competition_detail_and_404(ctx):
    detail = await ctx.client.get(f"/competitions/{ctx.competition_id}")
    assert detail.json()["name"] == "RDTEST League"
    assert (await ctx.client.get("/competitions/999999")).status_code == 404
