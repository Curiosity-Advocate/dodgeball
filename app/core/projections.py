"""Pure projection logic: fold the event log into a MatchState, and compute a
competition's standings from its finalised matches.

No I/O and no framework — these functions operate only on the domain dataclasses
in app.core.events, so they are exhaustively unit-testable without a database.
The same `apply` serves two callers: PostgresEventStore applies each new event to
the stored match_state row on append (incremental, write-through), and the
integration test folds the whole log to assert fold(log) == match_state.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import IntEnum

from app.core.events import Event, EventType, MatchState


def apply(state: MatchState, event: Event) -> MatchState:
    """Return the state after applying one event.

    Pure: `state` is frozen and never mutated — a new MatchState is returned.
    The update is per event type, and maintains the invariant
    current_round == score_home + score_away after every event:
      - round_won_home/away increment one score and the round together;
      - score_correction sets absolute scores and re-derives the round as N + M.
    """
    match event.type:
        case EventType.MATCH_STARTED:
            return replace(state, status="in_progress", version=event.version)

        case EventType.ROUND_WON_HOME:
            return replace(
                state,
                score_home=state.score_home + 1,
                current_round=state.current_round + 1,
                version=event.version,
            )

        case EventType.ROUND_WON_AWAY:
            return replace(
                state,
                score_away=state.score_away + 1,
                current_round=state.current_round + 1,
                version=event.version,
            )

        case EventType.SCORE_CORRECTION:
            score_home = event.payload["score_home"]
            score_away = event.payload["score_away"]
            return replace(
                state,
                score_home=score_home,
                score_away=score_away,
                current_round=score_home + score_away,
                version=event.version,
            )

        case EventType.MATCH_FINALISED:
            return replace(state, status="final", version=event.version)

        case _:
            raise ValueError(f"Unknown event type: {event.type}")


def fold(events: Iterable[Event], initial: MatchState | None = None) -> MatchState:
    """Fold events into a MatchState by applying them in order. Starting from the
    default MatchState rebuilds the projection from scratch — the rebuild path,
    and the basis of the fold(log) == match_state test.
    """
    state = initial if initial is not None else MatchState()
    for event in events:
        state = apply(state, event)
    return state


class Points(IntEnum):
    """Points awarded per match outcome (data-model.md)."""

    WIN = 3
    DRAW = 1
    LOSS = 0


@dataclass(frozen=True)
class MatchResult:
    """A finalised match's outcome — the input to a standings recompute."""

    home_team_id: int
    away_team_id: int
    score_home: int
    score_away: int


@dataclass(frozen=True)
class TeamStanding:
    """One team's row in a competition's points table.

    Draws aren't a stored column, so `played` may exceed `wins + losses`
    (the difference is draws).
    """

    competition_id: int
    team_id: int
    played: int = 0
    wins: int = 0
    losses: int = 0
    points: int = 0


def compute_standings(competition_id: int, results: Iterable[MatchResult]) -> list[TeamStanding]:
    """Compute a competition's standings from its finalised matches (full
    recompute). Pure: no I/O. Equal scores count as a draw.
    """
    standings: dict[int, TeamStanding] = {}

    def tally(team_id: int) -> TeamStanding:
        # the team's running total from earlier matches in this loop,
        # or a fresh zero row the first time we encounter them.
        return standings.get(team_id, TeamStanding(competition_id, team_id))

    for r in results:
        home, away = tally(r.home_team_id), tally(r.away_team_id)
        if r.score_home > r.score_away:
            home = replace(
                home,
                played=home.played + 1,
                wins=home.wins + 1,
                points=home.points + Points.WIN,
            )
            away = replace(
                away,
                played=away.played + 1,
                losses=away.losses + 1,
                points=away.points + Points.LOSS,
            )
        elif r.score_home < r.score_away:
            away = replace(
                away,
                played=away.played + 1,
                wins=away.wins + 1,
                points=away.points + Points.WIN,
            )
            home = replace(
                home,
                played=home.played + 1,
                losses=home.losses + 1,
                points=home.points + Points.LOSS,
            )
        else:  # draw
            home = replace(home, played=home.played + 1, points=home.points + Points.DRAW)
            away = replace(away, played=away.played + 1, points=away.points + Points.DRAW)
        standings[r.home_team_id], standings[r.away_team_id] = home, away

    return list(standings.values())
