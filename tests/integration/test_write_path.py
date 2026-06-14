"""Contract tests for the write path (management + scoring) against real Postgres."""

import os
import uuid
from dataclasses import dataclass

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.deps import get_assignment_service, get_management_service, get_scoring_service
from app.api.main import create_app
from app.auth.assignment import AssignmentService
from app.auth.tokens import create_access_token
from app.events.postgres import PostgresEventStore
from app.management.service import ManagementService
from app.scoring.service import ScoringService

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


@dataclass
class Ctx:
    client: httpx.AsyncClient
    admin: dict
    keeper: dict
    other: dict  # a scorekeeper never assigned to the match


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _event(type_: str, key: str, payload: dict | None = None) -> dict:
    return {"type": type_, "idempotency_key": key, "payload": payload or {}}


@pytest.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    try:
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except OperationalError:
        await eng.dispose()
        pytest.skip("database not reachable")
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM match_events WHERE match_id IN (SELECT id FROM matches "
                    "WHERE competition_id IN "
                    "(SELECT id FROM competitions WHERE name LIKE 'WPTEST%'))"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM standings WHERE competition_id IN "
                    "(SELECT id FROM competitions WHERE name LIKE 'WPTEST%')"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM matches WHERE competition_id IN "
                    "(SELECT id FROM competitions WHERE name LIKE 'WPTEST%')"
                )
            )
            await conn.execute(text("DELETE FROM teams WHERE name LIKE 'WPTEST%'"))
            await conn.execute(text("DELETE FROM competitions WHERE name LIKE 'WPTEST%'"))
            await conn.execute(text("DELETE FROM users WHERE email LIKE '%@wptest.local'"))
        await eng.dispose()


async def _make_user(engine, role: str) -> dict:
    email = f"{uuid.uuid4()}@wptest.local"
    async with engine.begin() as conn:
        uid = (
            await conn.execute(
                text(
                    "INSERT INTO users (email, password_hash, display_name, role) "
                    "VALUES (:e, 'x', 'WP', :r) RETURNING id"
                ),
                {"e": email, "r": role},
            )
        ).scalar_one()
    user_id = str(uid)
    return {"id": user_id, "token": create_access_token(user_id, role)}


@pytest.fixture
async def ctx(engine):
    app = create_app()
    app.dependency_overrides[get_management_service] = lambda: ManagementService(engine)
    app.dependency_overrides[get_assignment_service] = lambda: AssignmentService(engine)
    app.dependency_overrides[get_scoring_service] = lambda: ScoringService(
        PostgresEventStore(engine)
    )

    admin = await _make_user(engine, "admin")
    keeper = await _make_user(engine, "scorekeeper")
    other = await _make_user(engine, "scorekeeper")

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Ctx(client, admin, keeper, other)
    app.dependency_overrides.clear()


async def _make_match(ctx: Ctx) -> int:
    admin = _auth(ctx.admin["token"])
    comp = await ctx.client.post(
        "/competitions", headers=admin, json={"name": "WPTEST League", "level": "NATIONAL"}
    )
    home = await ctx.client.post("/teams", headers=admin, json={"name": "WPTEST Home"})
    away = await ctx.client.post("/teams", headers=admin, json={"name": "WPTEST Away"})
    match = await ctx.client.post(
        "/matches",
        headers=admin,
        json={
            "competition_id": comp.json()["id"],
            "home_team_id": home.json()["id"],
            "away_team_id": away.json()["id"],
        },
    )
    return match.json()["id"]


# ---- management contract ----


async def test_create_competition_requires_admin(ctx):
    r = await ctx.client.post(
        "/competitions",
        headers=_auth(ctx.keeper["token"]),
        json={"name": "WPTEST League", "level": "NATIONAL"},
    )
    assert r.status_code == 403


async def test_create_competition_unauthenticated_401(ctx):
    r = await ctx.client.post("/competitions", json={"name": "WPTEST League", "level": "NATIONAL"})
    assert r.status_code == 401


async def test_create_competition_admin_201(ctx):
    r = await ctx.client.post(
        "/competitions",
        headers=_auth(ctx.admin["token"]),
        json={"name": "WPTEST League", "level": "NATIONAL"},
    )
    assert r.status_code == 201
    assert r.json()["id"] > 0


async def test_create_match_distinct_teams_422(ctx):
    admin = _auth(ctx.admin["token"])
    comp = await ctx.client.post(
        "/competitions", headers=admin, json={"name": "WPTEST League", "level": "NATIONAL"}
    )
    team = await ctx.client.post("/teams", headers=admin, json={"name": "WPTEST Solo"})
    tid = team.json()["id"]
    r = await ctx.client.post(
        "/matches",
        headers=admin,
        json={"competition_id": comp.json()["id"], "home_team_id": tid, "away_team_id": tid},
    )
    assert r.status_code == 422


async def test_create_match_bad_reference_422(ctx):
    r = await ctx.client.post(
        "/matches",
        headers=_auth(ctx.admin["token"]),
        json={"competition_id": 999999, "home_team_id": 999998, "away_team_id": 999997},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_reference"


# ---- scoring contract ----


async def test_full_scoring_flow(ctx):
    match_id = await _make_match(ctx)
    assign = await ctx.client.put(
        f"/matches/{match_id}/scorekeeper",
        headers=_auth(ctx.admin["token"]),
        json={"user_id": ctx.keeper["id"]},
    )
    assert assign.status_code == 204

    sk = _auth(ctx.keeper["token"])
    start = await ctx.client.post(
        f"/matches/{match_id}/events", headers=sk, json=_event("match_started", str(uuid.uuid4()))
    )
    assert start.status_code == 201
    assert start.json()["state"]["status"] == "in_progress"

    r1 = await ctx.client.post(
        f"/matches/{match_id}/events", headers=sk, json=_event("round_won_home", str(uuid.uuid4()))
    )
    assert r1.status_code == 201
    assert r1.json()["state"]["score_home"] == 1
    assert r1.json()["state"]["version"] == 2


async def test_idempotent_replay_200(ctx):
    match_id = await _make_match(ctx)
    await ctx.client.put(
        f"/matches/{match_id}/scorekeeper",
        headers=_auth(ctx.admin["token"]),
        json={"user_id": ctx.keeper["id"]},
    )
    sk = _auth(ctx.keeper["token"])
    key = str(uuid.uuid4())
    first = await ctx.client.post(
        f"/matches/{match_id}/events", headers=sk, json=_event("match_started", key)
    )
    second = await ctx.client.post(
        f"/matches/{match_id}/events", headers=sk, json=_event("match_started", key)
    )
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["event"]["id"] == second.json()["event"]["id"]


async def test_post_event_not_assigned_403(ctx):
    match_id = await _make_match(ctx)
    await ctx.client.put(
        f"/matches/{match_id}/scorekeeper",
        headers=_auth(ctx.admin["token"]),
        json={"user_id": ctx.keeper["id"]},
    )
    r = await ctx.client.post(
        f"/matches/{match_id}/events",
        headers=_auth(ctx.other["token"]),
        json=_event("match_started", str(uuid.uuid4())),
    )
    assert r.status_code == 403


async def test_post_event_match_not_found_404(ctx):
    r = await ctx.client.post(
        "/matches/999999/events",
        headers=_auth(ctx.admin["token"]),
        json=_event("match_started", str(uuid.uuid4())),
    )
    assert r.status_code == 404


async def test_post_event_invalid_type_422(ctx):
    match_id = await _make_match(ctx)
    r = await ctx.client.post(
        f"/matches/{match_id}/events",
        headers=_auth(ctx.admin["token"]),
        json={"type": "goal_scored", "idempotency_key": str(uuid.uuid4()), "payload": {}},
    )
    assert r.status_code == 422


async def test_admin_can_score_without_assignment(ctx):
    match_id = await _make_match(ctx)  # no scorekeeper assigned
    r = await ctx.client.post(
        f"/matches/{match_id}/events",
        headers=_auth(ctx.admin["token"]),
        json=_event("match_started", str(uuid.uuid4())),
    )
    assert r.status_code == 201


async def test_score_correction_sets_state(ctx):
    match_id = await _make_match(ctx)
    admin = _auth(ctx.admin["token"])
    await ctx.client.post(
        f"/matches/{match_id}/events",
        headers=admin,
        json=_event("match_started", str(uuid.uuid4())),
    )
    r = await ctx.client.post(
        f"/matches/{match_id}/events",
        headers=admin,
        json=_event("score_correction", str(uuid.uuid4()), {"score_home": 3, "score_away": 2}),
    )
    assert r.status_code == 201
    assert r.json()["state"]["score_home"] == 3
    assert r.json()["state"]["current_round"] == 5  # re-derived as 3 + 2


async def test_score_correction_bad_payload_422(ctx):
    match_id = await _make_match(ctx)
    r = await ctx.client.post(
        f"/matches/{match_id}/events",
        headers=_auth(ctx.admin["token"]),
        json=_event("score_correction", str(uuid.uuid4()), {"score_home": "x"}),
    )
    assert r.status_code == 422
