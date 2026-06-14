"""ScoringService — the write path: append a scoring action via the EventStore.

Per module-boundaries, scoring depends on core + events only. Authorisation is
the API layer's job (via auth); this records the action and reports the outcome.
"""

from dataclasses import dataclass

from app.core.events import Event, EventType, MatchState, NewEvent
from app.events.store import EventStore


@dataclass(frozen=True)
class ScoringOutcome:
    event: Event
    created: bool  # True -> 201, False -> 200 (idempotent replay)
    state: MatchState


class ScoringService:
    def __init__(self, store: EventStore) -> None:
        self._store = store

    async def record(
        self,
        match_id: int,
        type: EventType,
        actor_id: str,
        idempotency_key: str,
        payload: dict,
    ) -> ScoringOutcome:
        result = await self._store.append(
            match_id,
            NewEvent(
                type=type, actor_id=actor_id, idempotency_key=idempotency_key, payload=payload
            ),
        )
        state = await self._store.snapshot(match_id)
        return ScoringOutcome(event=result.event, created=result.created, state=state)
