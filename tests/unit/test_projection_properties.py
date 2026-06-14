"""Property-based tests for the pure projection logic (testing-strategy.md).

Hypothesis generates many valid event logs and asserts model-level truths that
must hold for *all* of them — the folding/correction interleavings that fixed
examples can't enumerate. Pure and synchronous: no database, no event loop.
"""

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from app.core.events import Event, EventType
from app.core.projections import fold

_TS = datetime(2026, 1, 1, tzinfo=UTC)  # version drives state; the timestamp is inert here

# One scorekeeper action after the match starts.
_ops = st.one_of(
    st.just(("round_won_home", {})),
    st.just(("round_won_away", {})),
    st.builds(
        lambda h, a: ("score_correction", {"score_home": h, "score_away": a}),
        h=st.integers(min_value=0, max_value=50),
        a=st.integers(min_value=0, max_value=50),
    ),
)


@st.composite
def match_logs(draw) -> list[tuple[str, dict]]:
    """A valid log: match_started, then any mix of rounds/corrections, optional finalise."""
    middle = draw(st.lists(_ops, max_size=40))
    finalise = draw(st.booleans())
    return [("match_started", {})] + middle + ([("match_finalised", {})] if finalise else [])


def _to_events(ops: list[tuple[str, dict]]) -> list[Event]:
    return [
        Event(
            id=i,
            match_id=1,
            version=i,
            type=EventType(t),
            actor_id="a",
            idempotency_key=str(i),
            created_at=_TS,
            payload=p,
        )
        for i, (t, p) in enumerate(ops, start=1)
    ]


@given(ops=match_logs())
def test_round_equals_home_plus_away(ops):
    # The invariant apply() promises: current_round == score_home + score_away, always.
    state = fold(_to_events(ops))
    assert state.current_round == state.score_home + state.score_away


@given(ops=match_logs())
def test_final_version_tracks_log_length(ops):
    events = _to_events(ops)
    assert fold(events).version == len(events)


@given(ops=match_logs(), data=st.data())
def test_replay_from_any_snapshot_equals_full_fold(ops, data):
    # Snapshot+replay correctness (ADR-0010): folding from a mid-log snapshot must
    # land on the exact same state as folding the whole log from scratch.
    events = _to_events(ops)
    k = data.draw(st.integers(min_value=0, max_value=len(events)))
    snapshot = fold(events[:k])
    replayed = fold(events[k:], initial=snapshot)
    assert replayed == fold(events)


@given(h=st.integers(0, 50), a=st.integers(0, 50), ops=match_logs())
def test_correction_overrides_history(h, a, ops):
    # A correction sets absolute scores regardless of everything before it.
    events = _to_events(ops)
    correction = Event(
        id=len(events) + 1,
        match_id=1,
        version=len(events) + 1,
        type=EventType.SCORE_CORRECTION,
        actor_id="a",
        idempotency_key="c",
        created_at=_TS,
        payload={"score_home": h, "score_away": a},
    )
    state = fold([*events, correction])
    assert (state.score_home, state.score_away, state.current_round) == (h, a, h + a)
