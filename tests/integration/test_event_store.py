"""Integration tests for PostgresEventStore — against a real Postgres.

The shared `engine` fixture (conftest) truncates the database per test; each test
provisions its own competition / teams / match / user (committed, because the
store commits its own transactions).
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.events import EventType, NewEvent
from app.core.projections import fold
from app.events.postgres import PostgresEventStore


class _Fixture:
    def __init__(self, engine, store, match_id, actor_id, competition_id, home_id, away_id):
        self.engine = engine
        self.store = store
        self.match_id = match_id
        self.actor_id = actor_id
        self.competition_id = competition_id
        self.home_id = home_id
        self.away_id = away_id

    def new_event(self, type: EventType, payload: dict | None = None) -> NewEvent:
        return NewEvent(
            type=type,
            actor_id=self.actor_id,
            idempotency_key=str(uuid.uuid4()),
            payload=payload or {},
        )


@pytest.fixture
async def fx(engine):
    async with engine.begin() as conn:
        competition_id = (
            await conn.execute(
                text(
                    "INSERT INTO competitions (name, level) "
                    "VALUES ('ES Test League', 'NATIONAL') RETURNING id"
                )
            )
        ).scalar_one()
        home_id = (
            await conn.execute(text("INSERT INTO teams (name) VALUES ('ES Home') RETURNING id"))
        ).scalar_one()
        away_id = (
            await conn.execute(text("INSERT INTO teams (name) VALUES ('ES Away') RETURNING id"))
        ).scalar_one()
        match_id = (
            await conn.execute(
                text(
                    "INSERT INTO matches (competition_id, home_team_id, away_team_id) "
                    "VALUES (:c, :h, :a) RETURNING id"
                ),
                {"c": competition_id, "h": home_id, "a": away_id},
            )
        ).scalar_one()
        actor_id = (
            await conn.execute(
                text(
                    "INSERT INTO users (email, password_hash, display_name) "
                    "VALUES (:e, 'hash', 'ES Actor') RETURNING id"
                ),
                {"e": f"es-{uuid.uuid4()}@test.local"},
            )
        ).scalar_one()

    store = PostgresEventStore(engine)
    yield _Fixture(engine, store, match_id, str(actor_id), competition_id, home_id, away_id)


async def test_append_assigns_incrementing_version(fx):
    r1 = await fx.store.append(fx.match_id, fx.new_event(EventType.MATCH_STARTED))
    r2 = await fx.store.append(fx.match_id, fx.new_event(EventType.ROUND_WON_HOME))
    assert (r1.event.version, r1.created) == (1, True)
    assert (r2.event.version, r2.created) == (2, True)


async def test_idempotent_retry_returns_original(fx):
    event = fx.new_event(EventType.MATCH_STARTED)
    first = await fx.store.append(fx.match_id, event)
    second = await fx.store.append(fx.match_id, event)  # same idempotency_key
    assert first.created is True
    assert second.created is False  # idempotent replay, not a new append
    assert second.event.id == first.event.id
    assert second.event.version == first.event.version
    assert len(await fx.store.read_since(fx.match_id, 0)) == 1  # nothing appended twice
    state = await fx.store.snapshot(fx.match_id)
    assert state.version == 1  # the projection advanced once, not twice


async def test_fold_equals_match_state(fx):
    for t in (
        EventType.MATCH_STARTED,
        EventType.ROUND_WON_HOME,
        EventType.ROUND_WON_AWAY,
        EventType.ROUND_WON_HOME,
    ):
        await fx.store.append(fx.match_id, fx.new_event(t))
    # a correction mid-log exercises the interleaving the write-through must mirror
    await fx.store.append(
        fx.match_id,
        fx.new_event(EventType.SCORE_CORRECTION, {"score_home": 5, "score_away": 2}),
    )

    snapshot = await fx.store.snapshot(fx.match_id)
    rebuilt = fold(await fx.store.read_since(fx.match_id, 0))
    assert snapshot == rebuilt
    assert (snapshot.score_home, snapshot.score_away, snapshot.current_round) == (5, 2, 7)
    assert snapshot.version == 5


async def test_standings_recompute_on_finalise(fx):
    for t in (EventType.MATCH_STARTED, EventType.ROUND_WON_HOME, EventType.ROUND_WON_HOME):
        await fx.store.append(fx.match_id, fx.new_event(t))
    await fx.store.append(fx.match_id, fx.new_event(EventType.MATCH_FINALISED))  # home wins 2-0

    async with fx.engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT team_id, played, wins, losses, points FROM standings "
                    "WHERE competition_id = :c"
                ),
                {"c": fx.competition_id},
            )
        ).all()
    table = {r.team_id: r for r in rows}
    assert (table[fx.home_id].wins, table[fx.home_id].points) == (1, 3)
    assert (table[fx.away_id].losses, table[fx.away_id].points) == (1, 0)
