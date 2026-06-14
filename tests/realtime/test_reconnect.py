"""Headline real-time test (NFR-5): no event is missed across a disconnect.

WebSockets need Starlette's sync TestClient (httpx's ASGI transport can't drive
WS), so this module is sync. Test data is set up on a throwaway engine via
asyncio.run; during requests the app uses a lazily-built engine bound to the
TestClient's own event loop, plus one shared Dispatcher so the scoring POST
(publisher) and the WebSocket (subscriber) meet on the same hub.
"""

import asyncio
import os
import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.deps import (
    get_assignment_service,
    get_event_store,
    get_management_service,
    get_read_service,
    get_scoring_service,
)
from app.api.main import create_app
from app.auth.assignment import AssignmentService
from app.auth.tokens import create_access_token
from app.core.dispatcher import Dispatcher, get_dispatcher
from app.events.postgres import PostgresEventStore
from app.management.service import ManagementService
from app.read.service import ReadService
from app.scoring.service import ScoringService

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


@dataclass
class Env:
    client: TestClient
    match_id: int
    auth: dict


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _event(type_: str) -> dict:
    return {"type": type_, "idempotency_key": str(uuid.uuid4()), "payload": {}}


async def _setup() -> dict:
    """Create a competition, two teams, a match, and an assigned scorekeeper."""
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            comp = (
                await conn.execute(
                    text(
                        "INSERT INTO competitions (name, level) "
                        "VALUES ('WSTEST League', 'NATIONAL') RETURNING id"
                    )
                )
            ).scalar_one()
            home = (
                await conn.execute(
                    text("INSERT INTO teams (name) VALUES ('WSTEST Home') RETURNING id")
                )
            ).scalar_one()
            away = (
                await conn.execute(
                    text("INSERT INTO teams (name) VALUES ('WSTEST Away') RETURNING id")
                )
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
            keeper = (
                await conn.execute(
                    text(
                        "INSERT INTO users (email, password_hash, display_name, role) "
                        "VALUES (:e, 'x', 'WS', 'scorekeeper') RETURNING id"
                    ),
                    {"e": f"{uuid.uuid4()}@wstest.local"},
                )
            ).scalar_one()
            await conn.execute(
                text("INSERT INTO match_scorekeepers (match_id, user_id) VALUES (:m, :u)"),
                {"m": match, "u": keeper},
            )
    finally:
        await engine.dispose()
    return {"match_id": match, "keeper_id": str(keeper)}


async def _cleanup() -> None:
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM match_events WHERE match_id IN (SELECT id FROM matches "
                    "WHERE competition_id IN "
                    "(SELECT id FROM competitions WHERE name LIKE 'WSTEST%'))"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM matches WHERE competition_id IN "
                    "(SELECT id FROM competitions WHERE name LIKE 'WSTEST%')"
                )
            )
            await conn.execute(text("DELETE FROM teams WHERE name LIKE 'WSTEST%'"))
            await conn.execute(text("DELETE FROM competitions WHERE name LIKE 'WSTEST%'"))
            await conn.execute(text("DELETE FROM users WHERE email LIKE '%@wstest.local'"))
    finally:
        await engine.dispose()


@pytest.fixture
def env():
    try:
        ctx = asyncio.run(_setup())
    except OperationalError:
        pytest.skip("database not reachable")

    dispatcher = Dispatcher()
    holder: dict = {}

    def _engine():
        # Built on first request, inside the TestClient's event loop, so the
        # asyncpg pool is bound to the loop that actually runs the app.
        if "engine" not in holder:
            holder["engine"] = create_async_engine(DATABASE_URL)
        return holder["engine"]

    app = create_app()
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_event_store] = lambda: PostgresEventStore(_engine())
    app.dependency_overrides[get_scoring_service] = lambda: ScoringService(
        PostgresEventStore(_engine(), dispatcher)
    )
    app.dependency_overrides[get_read_service] = lambda: ReadService(_engine())
    app.dependency_overrides[get_management_service] = lambda: ManagementService(_engine())
    app.dependency_overrides[get_assignment_service] = lambda: AssignmentService(_engine())

    token = create_access_token(ctx["keeper_id"], "scorekeeper")
    try:
        with TestClient(app) as client:
            yield Env(client, ctx["match_id"], _auth(token))
    finally:
        app.dependency_overrides.clear()
        asyncio.run(_cleanup())


def _score(env: Env, type_: str) -> None:
    r = env.client.post(f"/matches/{env.match_id}/events", headers=env.auth, json=_event(type_))
    assert r.status_code == 201


def test_reconnect_replays_missed_events(env):
    """The headline guarantee: a client that disconnects, while scoring
    continues, sees every missed event on reconnect (NFR-5) — via replay."""
    # Two events happen before anyone is watching; they live in the log.
    _score(env, "match_started")  # v1
    _score(env, "round_won_home")  # v2

    with env.client.websocket_connect(f"/matches/{env.match_id}") as ws:
        ws.send_json({"last_version": 0})
        assert ws.receive_json()["version"] == 1  # replayed
        assert ws.receive_json()["version"] == 2
        _score(env, "round_won_away")  # v3, live
        assert ws.receive_json()["version"] == 3
    # ws closed -> the viewer is "disconnected"

    # Scoring continues while no one is connected.
    _score(env, "round_won_home")  # v4
    _score(env, "round_won_home")  # v5

    # Reconnect from where we left off: the gap (v4, v5) is replayed in order.
    with env.client.websocket_connect(f"/matches/{env.match_id}") as ws:
        ws.send_json({"last_version": 3})
        v4 = ws.receive_json()
        v5 = ws.receive_json()

    assert [v4["version"], v5["version"]] == [4, 5]  # zero missed
    assert v5["state"]["score_home"] == 3  # home won rounds v2, v4, v5
    assert v5["state"]["score_away"] == 1  # away won round v3


def test_snapshot_then_live(env):
    """The other reconnect path: take a snapshot, then stream from its version
    onward — no replay, only newer live events."""
    _score(env, "match_started")  # v1
    _score(env, "round_won_home")  # v2
    _score(env, "round_won_home")  # v3

    snap = env.client.get(f"/matches/{env.match_id}/snapshot").json()
    assert snap["version"] == 3
    assert snap["score_home"] == 2

    with env.client.websocket_connect(f"/matches/{env.match_id}") as ws:
        ws.send_json({"last_version": snap["version"]})  # caught up -> nothing replayed
        _score(env, "round_won_away")  # v4, live
        live = ws.receive_json()

    assert live["version"] == 4
    assert live["state"]["score_away"] == 1
