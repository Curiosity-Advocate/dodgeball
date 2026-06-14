"""Shared FastAPI dependencies."""

from fastapi import Depends, Request

from app.auth.assignment import AssignmentService
from app.auth.errors import InvalidAccessToken, NotAuthorized
from app.auth.ratelimit import RateLimiter
from app.auth.service import AuthService
from app.auth.tokens import AccessTokenClaims, decode_access_token
from app.core.config import get_settings
from app.core.db import get_engine
from app.events.postgres import PostgresEventStore
from app.management.errors import MatchNotFound
from app.management.service import ManagementService
from app.scoring.service import ScoringService

# Process-wide auth limiter (single instance, in-memory). Exposed via a
# dependency so tests can override it with a fresh/strict limiter.
_settings = get_settings()
_auth_limiter = RateLimiter(_settings.auth_rate_limit_attempts, _settings.auth_rate_limit_window)


def get_auth_service() -> AuthService:
    return AuthService(get_engine())


def get_management_service() -> ManagementService:
    return ManagementService(get_engine())


def get_assignment_service() -> AssignmentService:
    return AssignmentService(get_engine())


def get_scoring_service() -> ScoringService:
    return ScoringService(PostgresEventStore(get_engine()))


def get_rate_limiter() -> RateLimiter:
    return _auth_limiter


def get_current_user(request: Request) -> AccessTokenClaims:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise InvalidAccessToken("missing bearer token")
    return decode_access_token(token)


def require_admin(claims: AccessTokenClaims = Depends(get_current_user)) -> AccessTokenClaims:
    if claims.role != "admin":
        raise NotAuthorized("admin role required")
    return claims


async def require_match_writer(
    match_id: int,
    claims: AccessTokenClaims = Depends(get_current_user),
    mgmt: ManagementService = Depends(get_management_service),
    assignment: AssignmentService = Depends(get_assignment_service),
) -> AccessTokenClaims:
    """Allow the request only if the match exists (else 404) and the caller is an
    admin or the match's assigned scorekeeper (else 403).
    """
    if not await mgmt.match_exists(match_id):
        raise MatchNotFound()
    if claims.role != "admin":
        scorekeeper_id = await assignment.get_scorekeeper(match_id)
        if claims.user_id != scorekeeper_id:
            raise NotAuthorized("not the assigned scorekeeper")
    return claims
