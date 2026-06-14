"""Refresh tokens: issue, rotate, revoke, with reuse detection (ADR-0007, NFR-11).

Opaque random values; only their sha256 hash is stored. Each refresh rotates: the
old row is marked replaced (replaced_by -> new) and a new token issued. Presenting
an already-replaced token is treated as theft and revokes the whole forward chain
via a recursive CTE. The sole accessor of refresh_tokens; AuthService orchestrates.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.auth.errors import InvalidRefreshToken, RefreshTokenReused
from app.core.config import get_settings


@dataclass(frozen=True)
class RotatedToken:
    raw: str  # the new token, returned to the client once; never stored
    user_id: str  # owner, so the caller can mint the matching access token


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class RefreshTokenStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def issue(self, user_id: str) -> str:
        """Create a new active refresh token for the user; return the raw value."""
        async with self._engine.begin() as conn:
            raw, _ = await self._issue(conn, user_id)
            return raw

    async def rotate(self, raw: str) -> RotatedToken:
        """Validate + rotate in one transaction.

        Raises RefreshTokenReused (chain revoked) if the token was already
        replaced, or InvalidRefreshToken if unknown / expired / revoked.
        """
        reused = False
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, user_id, expires_at, revoked_at, replaced_by "
                        "FROM refresh_tokens WHERE token_hash = :h"
                    ),
                    {"h": _hash(raw)},
                )
            ).one_or_none()

            if row is None:
                raise InvalidRefreshToken("unknown token")
            if row.replaced_by is not None:
                # Reuse: revoke the chain and let this transaction COMMIT before
                # raising — raising inside the block would roll the revocation back.
                await self._revoke_chain(conn, row.id)
                reused = True
            elif row.revoked_at is not None:
                raise InvalidRefreshToken("revoked token")
            elif row.expires_at <= datetime.now(UTC):
                raise InvalidRefreshToken("expired token")
            else:
                new_raw, new_id = await self._issue(conn, str(row.user_id))
                await conn.execute(
                    text(
                        "UPDATE refresh_tokens SET replaced_by = :new, revoked_at = now() "
                        "WHERE id = :old"
                    ),
                    {"new": new_id, "old": row.id},
                )
                return RotatedToken(raw=new_raw, user_id=str(row.user_id))

        # The block has committed the chain revocation; now signal the theft.
        if reused:
            raise RefreshTokenReused("token already rotated")

    async def revoke(self, raw: str) -> None:
        """Revoke a token (logout). No-op if unknown or already revoked."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE token_hash = :h AND revoked_at IS NULL"
                ),
                {"h": _hash(raw)},
            )

    # ---- helpers ----

    async def _issue(self, conn: AsyncConnection, user_id: str) -> tuple[str, int]:
        raw = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=get_settings().refresh_token_ttl)
        new_id = (
            await conn.execute(
                text(
                    "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
                    "VALUES (CAST(:user_id AS uuid), :hash, :expires_at) RETURNING id"
                ),
                {"user_id": user_id, "hash": _hash(raw), "expires_at": expires_at},
            )
        ).scalar_one()
        return raw, new_id

    async def _revoke_chain(self, conn: AsyncConnection, start_id: int) -> None:
        """Revoke the reused token and its forward replaced_by lineage."""
        await conn.execute(
            text("""
                WITH RECURSIVE chain AS (
                    SELECT id, replaced_by FROM refresh_tokens WHERE id = :start
                    UNION ALL
                    SELECT rt.id, rt.replaced_by
                    FROM refresh_tokens rt
                    JOIN chain c ON rt.id = c.replaced_by
                )
                UPDATE refresh_tokens
                SET revoked_at = now()
                WHERE id IN (SELECT id FROM chain) AND revoked_at IS NULL
            """),
            {"start": start_id},
        )
