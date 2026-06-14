"""Admin management router: competitions, teams, matches, scorekeeper assignment."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import get_assignment_service, get_management_service, require_admin
from app.auth.assignment import AssignmentService
from app.auth.tokens import AccessTokenClaims
from app.management.errors import MatchNotFound
from app.management.service import Competition, ManagementService, Match, Team

router = APIRouter(tags=["management"])


class CreateCompetitionRequest(BaseModel):
    name: str = Field(min_length=1)
    level: Literal["NATIONAL", "STATE", "INTERNATIONAL", "LOCAL"]
    season: str | None = None


class CreateTeamRequest(BaseModel):
    name: str = Field(min_length=1)


class CreateMatchRequest(BaseModel):
    competition_id: int
    home_team_id: int
    away_team_id: int
    scheduled_at: datetime | None = None

    @model_validator(mode="after")
    def _teams_differ(self) -> "CreateMatchRequest":
        if self.home_team_id == self.away_team_id:
            raise ValueError("home and away teams must differ")
        return self


class AssignScorekeeperRequest(BaseModel):
    user_id: str


@router.post("/competitions", status_code=status.HTTP_201_CREATED)
async def create_competition(
    body: CreateCompetitionRequest,
    _: AccessTokenClaims = Depends(require_admin),
    mgmt: ManagementService = Depends(get_management_service),
) -> Competition:
    return await mgmt.create_competition(body.name, body.level, body.season)


@router.post("/teams", status_code=status.HTTP_201_CREATED)
async def create_team(
    body: CreateTeamRequest,
    _: AccessTokenClaims = Depends(require_admin),
    mgmt: ManagementService = Depends(get_management_service),
) -> Team:
    return await mgmt.create_team(body.name)


@router.post("/matches", status_code=status.HTTP_201_CREATED)
async def create_match(
    body: CreateMatchRequest,
    _: AccessTokenClaims = Depends(require_admin),
    mgmt: ManagementService = Depends(get_management_service),
) -> Match:
    return await mgmt.create_match(
        body.competition_id, body.home_team_id, body.away_team_id, body.scheduled_at
    )


@router.put("/matches/{match_id}/scorekeeper", status_code=status.HTTP_204_NO_CONTENT)
async def assign_scorekeeper(
    match_id: int,
    body: AssignScorekeeperRequest,
    claims: AccessTokenClaims = Depends(require_admin),
    mgmt: ManagementService = Depends(get_management_service),
    assignment: AssignmentService = Depends(get_assignment_service),
) -> None:
    if not await mgmt.match_exists(match_id):
        raise MatchNotFound()
    await assignment.assign(match_id, body.user_id, assigned_by=claims.user_id)


@router.delete("/matches/{match_id}/scorekeeper", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_scorekeeper(
    match_id: int,
    claims: AccessTokenClaims = Depends(require_admin),
    mgmt: ManagementService = Depends(get_management_service),
    assignment: AssignmentService = Depends(get_assignment_service),
) -> None:
    if not await mgmt.match_exists(match_id):
        raise MatchNotFound()
    await assignment.unassign(match_id)
