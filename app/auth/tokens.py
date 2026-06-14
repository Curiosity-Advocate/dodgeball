"""JWT access tokens (ADR-0007).

Short-lived, stateless, signed with HS256 using the configured secret. Carries
the user's identity (sub) and role so any instance verifies by signature alone,
with no database lookup.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.auth.errors import InvalidAccessToken
from app.core.config import get_settings

_ALGORITHM = "HS256"


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: str
    role: str


def create_access_token(user_id: str, role: str) -> str:
    """Mint a signed access token for the user, expiring after access_token_ttl."""
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> AccessTokenClaims:
    """Verify signature + expiry and return the identity claims.

    Raises InvalidAccessToken on any failure (bad signature, expired, malformed).
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidAccessToken(str(exc)) from exc
    return AccessTokenClaims(user_id=payload["sub"], role=payload["role"])
