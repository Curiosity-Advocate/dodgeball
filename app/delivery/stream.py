"""Delivery: format live updates and stream them to a WebSocket connection.

Uses only core (the dispatcher's MatchUpdate) + the WebSocket. Replay-on-connect
(reading the log) is the api route's job; it hands the resulting watermark here.
"""

import asyncio

from fastapi import WebSocket

from app.core.dispatcher import MatchUpdate
from app.core.events import Event, MatchState


def format_message(event: Event, state: MatchState) -> dict:
    """The server -> client wire message (api-contract.md)."""
    return {
        "version": event.version,
        "type": event.type,
        "payload": event.payload,
        "state": {
            "score_home": state.score_home,
            "score_away": state.score_away,
            "current_round": state.current_round,
            "status": state.status,
        },
    }


async def _pump(websocket: WebSocket, mailbox: asyncio.Queue[MatchUpdate], last_sent: int) -> None:
    """Forward live updates in version order, skipping any version already sent
    during replay (dedupe by version)."""
    while True:
        update = await mailbox.get()
        if update.event.version <= last_sent:
            continue
        await websocket.send_json(format_message(update.event, update.state))
        last_sent = update.event.version


async def _watch_disconnect(websocket: WebSocket) -> None:
    """Return when the client disconnects (clients send nothing after the handshake)."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


async def serve_live(
    websocket: WebSocket, mailbox: asyncio.Queue[MatchUpdate], last_sent: int
) -> None:
    """Stream live updates until the client disconnects, then return cleanly.

    Races the pump (mailbox -> socket) against a disconnect watcher so a client
    that leaves while idle is noticed at once, instead of leaving the pump parked
    on an empty mailbox.
    """
    tasks = {
        asyncio.create_task(_pump(websocket, mailbox, last_sent)),
        asyncio.create_task(_watch_disconnect(websocket)),
    }
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        if (exc := task.exception()) is not None:
            raise exc
