"""Domain types for the event-sourced match model.

Pure, framework-free value objects: the event log and the match-state projection
as immutable dataclasses. They carry no database or I/O concerns — `app.events`
maps database rows to and from these types, and `app.core.projections` folds a
sequence of events into a MatchState. Keeping them dependency-free here is what
lets the fold logic be unit-tested without a database (module-boundaries.md).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EventType(StrEnum):
    """The five scoring events. Values mirror the match_events.type CHECK in
    data-model.md exactly, so the enum and the database agree on the strings."""

    MATCH_STARTED = "match_started"
    ROUND_WON_HOME = "round_won_home"
    ROUND_WON_AWAY = "round_won_away"
    SCORE_CORRECTION = "score_correction"
    MATCH_FINALISED = "match_finalised"


@dataclass(frozen=True)
class NewEvent:
    """An event to be appended — only the caller-supplied fields. The store
    assigns id, version, and created_at, returning a full Event.
    """

    type: EventType
    actor_id: str
    idempotency_key: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Event:
    """One immutable row of the match_events log.

    `id` is the global BIGINT order; `version` is the per-match cursor. `payload`
    mirrors the JSONB column (only score_correction populates it in v1.0).
    """

    id: int
    match_id: int
    version: int
    type: EventType
    actor_id: str
    idempotency_key: str
    created_at: datetime
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MatchState:
    """The match_state projection: current score/round/status plus the version of
    the last event applied. A snapshot is self-describing — state plus its cursor.
    """

    score_home: int = 0
    score_away: int = 0
    current_round: int = 0
    status: str = "scheduled"
    version: int = 0
