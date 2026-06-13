"""The EventStore interface — the only sanctioned path to the match_events log.

Per ADR-0003 every read and write of the event log goes through this abstraction,
so a future Postgres-outbox -> Kafka move is localised to the implementation and
call sites are untouched. PostgresEventStore (postgres.py) is the v1.0 concrete
implementation; tests can substitute a fake.
"""

from abc import ABC, abstractmethod

from app.core.events import Event, MatchState, NewEvent


class EventStore(ABC):
    @abstractmethod
    async def append(self, match_id: int, event: NewEvent) -> Event:
        """Append one event to a match's log and return the stored Event.

        Assigns the next contiguous per-match version. Idempotent: if an event
        with the same idempotency_key already exists, the original Event is
        returned and nothing is appended (ADR-0005).
        """
        ...

    @abstractmethod
    async def read_since(self, match_id: int, version: int) -> list[Event]:
        """Return the match's events with version > the given cursor, in order.
        The replay path for reconnect; version 0 returns the whole log.
        """
        ...

    @abstractmethod
    async def snapshot(self, match_id: int) -> MatchState:
        """Return the current match_state projection (state plus the version it
        reflects) — an O(1) read of the stored row.
        """
        ...
