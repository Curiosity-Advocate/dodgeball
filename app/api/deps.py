"""Shared FastAPI dependencies."""

from fastapi import Request

from app.auth.errors import InvalidAccessToken
from app.auth.ratelimit import RateLimiter
from app.auth.service import AuthService
from app.auth.tokens import AccessTokenClaims, decode_access_token
from app.core.config import get_settings
from app.core.db import get_engine

# Process-wide auth limiter (single instance, in-memory — D3). Exposed via a
# dependency so tests can override it with a fresh/strict limiter.
_settings = get_settings()
_auth_limiter = RateLimiter(_settings.auth_rate_limit_attempts, _settings.auth_rate_limit_window)


def get_auth_service() -> AuthService:
    return AuthService(get_engine())


def get_rate_limiter() -> RateLimiter:
    return _auth_limiter


def get_current_user(request: Request) -> AccessTokenClaims:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise InvalidAccessToken("missing bearer token")
    return decode_access_token(token)
