"""In-process pub/sub for live match updates (ADR-0006).

A single process-wide hub. WebSocket connections subscribe to a match and get a
per-connection mailbox (a bounded asyncio.Queue); the EventStore publishes a
MatchUpdate after each committed append. Fan-out is best-effort: a slow consumer's
full mailbox drops its oldest message (NFR-7), recovered later via version-gap replay.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from app.core.events import Event, MatchState

_MAILBOX_SIZE = 256


@dataclass(frozen=True)
class MatchUpdate:
    """Published per appended event: the event and the state resulting from it."""

    event: Event
    state: MatchState


class Dispatcher:
    def __init__(self, mailbox_size: int = _MAILBOX_SIZE) -> None:
        self._mailbox_size = mailbox_size
        self._subscribers: dict[int, set[asyncio.Queue[MatchUpdate]]] = defaultdict(set)

    def subscribe(self, match_id: int) -> asyncio.Queue[MatchUpdate]:
        mailbox: asyncio.Queue[MatchUpdate] = asyncio.Queue(maxsize=self._mailbox_size)
        self._subscribers[match_id].add(mailbox)
        return mailbox

    def unsubscribe(self, match_id: int, mailbox: asyncio.Queue[MatchUpdate]) -> None:
        subscribers = self._subscribers.get(match_id)
        if subscribers is None:
            return
        subscribers.discard(mailbox)
        if not subscribers:
            del self._subscribers[match_id]

    def publish(self, match_id: int, update: MatchUpdate) -> None:
        # Synchronous and await-free: in a single event loop nothing interleaves
        # between full()/get_nowait()/put_nowait(), so drop-oldest is race-free.
        for mailbox in self._subscribers.get(match_id, ()):
            if mailbox.full():
                mailbox.get_nowait()  # drop the oldest unread (best-effort)
            mailbox.put_nowait(update)


@lru_cache
def get_dispatcher() -> Dispatcher:
    return Dispatcher()
