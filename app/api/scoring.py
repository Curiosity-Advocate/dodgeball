"""Scoring router: POST /matches/{id}/events (the authenticated write path)."""

from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.deps import get_scoring_service, require_match_writer
from app.auth.tokens import AccessTokenClaims
from app.core.events import EventType
from app.scoring.service import ScoringService

router = APIRouter(tags=["scoring"])


class PostEventRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "round_won_home",
                "payload": {},
                "idempotency_key": "11111111-1111-1111-1111-111111111111",
            }
        }
    )

    type: Literal[
        "match_started",
        "round_won_home",
        "round_won_away",
        "score_correction",
        "match_finalised",
    ]
    payload: dict = Field(default_factory=dict)
    idempotency_key: str

    @model_validator(mode="after")
    def _check_correction_payload(self) -> "PostEventRequest":
        if self.type == "score_correction":
            home, away = self.payload.get("score_home"), self.payload.get("score_away")
            if not isinstance(home, int) or not isinstance(away, int):
                raise ValueError("score_correction requires integer score_home and score_away")
        return self


@router.post("/matches/{match_id}/events")
async def post_event(
    match_id: int,
    body: PostEventRequest,
    response: Response,
    claims: AccessTokenClaims = Depends(require_match_writer),
    scoring: ScoringService = Depends(get_scoring_service),
) -> dict:
    outcome = await scoring.record(
        match_id, EventType(body.type), claims.user_id, body.idempotency_key, body.payload
    )
    # 201 for a new append, 200 for an idempotent replay of an existing event.
    response.status_code = status.HTTP_201_CREATED if outcome.created else status.HTTP_200_OK
    return {
        "event": {
            "id": outcome.event.id,
            "version": outcome.event.version,
            "type": outcome.event.type,
            "payload": outcome.event.payload,
            "created_at": outcome.event.created_at,
        },
        "state": {
            "score_home": outcome.state.score_home,
            "score_away": outcome.state.score_away,
            "current_round": outcome.state.current_round,
            "status": outcome.state.status,
            "version": outcome.state.version,
        },
    }
