"""WebSocket route: live match feed with subscribe-before-replay reconnect."""

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import get_event_store
from app.core.dispatcher import Dispatcher, get_dispatcher
from app.core.events import MatchState
from app.core.projections import apply
from app.delivery.stream import format_message, serve_live
from app.events.store import EventStore

router = APIRouter()


@router.websocket("/matches/{match_id}")
async def match_feed(
    websocket: WebSocket,
    match_id: int,
    dispatcher: Dispatcher = Depends(get_dispatcher),
    store: EventStore = Depends(get_event_store),
) -> None:
    await websocket.accept()
    mailbox = dispatcher.subscribe(match_id)  # subscribe BEFORE replay — no gap
    try:
        handshake = await websocket.receive_json()
        last_version = int(handshake.get("last_version", 0)) if isinstance(handshake, dict) else 0
        last_sent = await _replay(websocket, store, match_id, last_version)
        await serve_live(websocket, mailbox, last_sent)
    except WebSocketDisconnect:
        pass
    finally:
        dispatcher.unsubscribe(match_id, mailbox)


async def _replay(websocket: WebSocket, store: EventStore, match_id: int, last_version: int) -> int:
    """Send events with version > last_version, each with its folded state.
    Returns the highest version sent (the dedupe watermark for live)."""
    state = MatchState()
    last_sent = last_version
    for event in await store.read_since(match_id, 0):
        state = apply(state, event)  # fold every event to get correct running state
        if event.version > last_version:  # but only send the ones the client missed
            await websocket.send_json(format_message(event, state))
            last_sent = event.version
    return last_sent
