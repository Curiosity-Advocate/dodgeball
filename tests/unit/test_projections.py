"""Unit tests for the pure projection logic — no database."""

from datetime import UTC, datetime

from app.core.events import Event, EventType, MatchState
from app.core.projections import MatchResult, TeamStanding, apply, compute_standings, fold

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _event(version: int, type: EventType, payload: dict | None = None) -> Event:
    return Event(
        id=version,
        match_id=1,
        version=version,
        type=type,
        actor_id=_ZERO_UUID,
        idempotency_key=_ZERO_UUID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload or {},
    )


def test_match_started_sets_in_progress():
    state = apply(MatchState(), _event(1, EventType.MATCH_STARTED))
    assert state.status == "in_progress"
    assert state.version == 1


def test_round_won_home_increments_score_and_round():
    state = apply(MatchState(), _event(1, EventType.ROUND_WON_HOME))
    assert (state.score_home, state.score_away, state.current_round) == (1, 0, 1)


def test_round_won_away_increments_score_and_round():
    state = apply(MatchState(), _event(1, EventType.ROUND_WON_AWAY))
    assert (state.score_home, state.score_away, state.current_round) == (0, 1, 1)


def test_score_correction_sets_absolute_and_rederives_round():
    state = apply(
        MatchState(score_home=5, score_away=2, current_round=7),
        _event(8, EventType.SCORE_CORRECTION, {"score_home": 3, "score_away": 1}),
    )
    assert state.score_home == 3
    assert state.score_away == 1
    assert state.current_round == 4  # re-derived as 3 + 1, not incremented from 7


def test_match_finalised_sets_final():
    state = apply(MatchState(status="in_progress"), _event(1, EventType.MATCH_FINALISED))
    assert state.status == "final"


def test_fold_replays_full_log():
    events = [
        _event(1, EventType.MATCH_STARTED),
        _event(2, EventType.ROUND_WON_HOME),
        _event(3, EventType.ROUND_WON_AWAY),
        _event(4, EventType.ROUND_WON_HOME),
        _event(5, EventType.MATCH_FINALISED),
    ]
    assert fold(events) == MatchState(
        score_home=2, score_away=1, current_round=3, status="final", version=5
    )


def test_apply_does_not_mutate_input():
    original = MatchState()
    apply(original, _event(1, EventType.ROUND_WON_HOME))
    assert original == MatchState()  # frozen — the input is untouched


def test_compute_standings_win_and_loss():
    results = [MatchResult(home_team_id=10, away_team_id=20, score_home=3, score_away=1)]
    table = {s.team_id: s for s in compute_standings(1, results)}
    assert table[10] == TeamStanding(1, 10, played=1, wins=1, losses=0, points=3)
    assert table[20] == TeamStanding(1, 20, played=1, wins=0, losses=1, points=0)


def test_compute_standings_draw():
    table = {s.team_id: s for s in compute_standings(1, [MatchResult(10, 20, 2, 2)])}
    assert table[10] == TeamStanding(1, 10, played=1, wins=0, losses=0, points=1)
    assert table[20] == TeamStanding(1, 20, played=1, wins=0, losses=0, points=1)


def test_compute_standings_accumulates_across_matches():
    results = [
        MatchResult(10, 20, 3, 1),  # team 10 beats 20
        MatchResult(10, 30, 0, 2),  # team 30 beats 10
    ]
    table = {s.team_id: s for s in compute_standings(1, results)}
    assert table[10] == TeamStanding(1, 10, played=2, wins=1, losses=1, points=3)
