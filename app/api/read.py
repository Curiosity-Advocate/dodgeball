"""Public read router: snapshot, replay, standings, match list/filter, entity detail."""

from datetime import date as date_type
from typing import Any, Literal

from fastapi import APIRouter, Depends

from app.api.deps import get_event_store, get_read_service
from app.events.store import EventStore
from app.read.errors import NotFound
from app.read.service import ReadService

router = APIRouter(tags=["read"])


@router.get("/matches/{match_id}/snapshot")
async def get_snapshot(
    match_id: int,
    read: ReadService = Depends(get_read_service),
    store: EventStore = Depends(get_event_store),
) -> dict[str, Any]:
    if not await read.match_exists(match_id):
        raise NotFound("match not found")
    state = await store.snapshot(match_id)
    return {
        "match_id": match_id,
        "score_home": state.score_home,
        "score_away": state.score_away,
        "current_round": state.current_round,
        "status": state.status,
        "version": state.version,
    }


@router.get("/matches/{match_id}/events")
async def get_events(
    match_id: int,
    since: int = 0,
    read: ReadService = Depends(get_read_service),
    store: EventStore = Depends(get_event_store),
) -> dict[str, Any]:
    if not await read.match_exists(match_id):
        raise NotFound("match not found")
    events = await store.read_since(match_id, since)
    return {
        "events": [
            {"version": e.version, "type": e.type, "payload": e.payload, "created_at": e.created_at}
            for e in events
        ]
    }


@router.get("/competitions/{competition_id}/standings")
async def get_standings(
    competition_id: int,
    read: ReadService = Depends(get_read_service),
) -> dict[str, Any]:
    return {"standings": await read.standings(competition_id)}


@router.get("/matches")
async def list_matches(
    team: int | None = None,
    competition: int | None = None,
    date: date_type | None = None,
    status: Literal["scheduled", "in_progress", "final"] | None = None,
    read: ReadService = Depends(get_read_service),
) -> dict[str, Any]:
    matches = await read.list_matches(
        team=team, competition=competition, match_date=date, status=status
    )
    return {"matches": matches}


@router.get("/matches/{match_id}")
async def get_match(match_id: int, read: ReadService = Depends(get_read_service)) -> dict[str, Any]:
    return await read.get_match(match_id)


@router.get("/teams/{team_id}")
async def get_team(team_id: int, read: ReadService = Depends(get_read_service)) -> dict[str, Any]:
    return await read.get_team(team_id)


@router.get("/competitions/{competition_id}")
async def get_competition(
    competition_id: int, read: ReadService = Depends(get_read_service)
) -> dict[str, Any]:
    return await read.get_competition(competition_id)
