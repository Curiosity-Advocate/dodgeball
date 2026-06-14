"""AuthService — orchestrates registration, login, refresh, and logout.

Holds the engine and composes the auth primitives: argon2 password hashing, JWT
access tokens, and the rotating refresh-token store. The sole accessor of the
users table.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.errors import (
    EmailAlreadyExists,
    InvalidAccessToken,
    InvalidCredentials,
    InvalidRefreshToken,
)
from app.auth.passwords import hash_password, verify_password
from app.auth.refresh import RefreshTokenStore
from app.auth.tokens import create_access_token
from app.core.config import get_settings

_USER_COLUMNS = "id, email, display_name, role, is_active, created_at"

# Pre-computed hash to verify against when the email is unknown, so login costs
# the same whether or not the account exists (defeats user enumeration by timing).
_DUMMY_HASH = hash_password("dummy-password-for-constant-time-login")


@dataclass(frozen=True)
class User:
    id: str
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _row_to_user(row) -> User:
    return User(
        id=str(row.id),
        email=row.email,
        display_name=row.display_name,
        role=row.role,
        is_active=row.is_active,
        created_at=row.created_at,
    )


class AuthService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._refresh = RefreshTokenStore(engine)

    async def register(self, email: str, password: str, display_name: str) -> User:
        try:
            async with self._engine.begin() as conn:
                row = (
                    await conn.execute(
                        text(
                            "INSERT INTO users (email, password_hash, display_name) "
                            "VALUES (:email, :hash, :display_name) "
                            f"RETURNING {_USER_COLUMNS}"
                        ),
                        {
                            "email": email,
                            "hash": hash_password(password),
                            "display_name": display_name,
                        },
                    )
                ).one()
        except IntegrityError as exc:
            raise EmailAlreadyExists() from exc
        return _row_to_user(row)

    async def login(self, email: str, password: str) -> TokenPair:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, password_hash, role, is_active FROM users WHERE email = :email"
                    ),
                    {"email": email},
                )
            ).one_or_none()

        if row is None:
            verify_password(password, _DUMMY_HASH)  # equalise timing vs. a real account
            raise InvalidCredentials()
        if not row.is_active or not verify_password(password, row.password_hash):
            raise InvalidCredentials()

        return await self._issue_pair(str(row.id), row.role)

    async def refresh(self, raw_refresh_token: str) -> TokenPair:
        rotated = await self._refresh.rotate(raw_refresh_token)
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT role FROM users WHERE id = CAST(:id AS uuid)"),
                    {"id": rotated.user_id},
                )
            ).one_or_none()
        if row is None:
            raise InvalidRefreshToken("user no longer exists")
        access = create_access_token(rotated.user_id, row.role)
        return TokenPair(access, rotated.raw, get_settings().access_token_ttl)

    async def logout(self, raw_refresh_token: str) -> None:
        await self._refresh.revoke(raw_refresh_token)

    async def get_user(self, user_id: str) -> User:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(f"SELECT {_USER_COLUMNS} FROM users WHERE id = CAST(:id AS uuid)"),
                    {"id": user_id},
                )
            ).one_or_none()
        if row is None:
            raise InvalidAccessToken("user no longer exists")
        return _row_to_user(row)

    async def _issue_pair(self, user_id: str, role: str) -> TokenPair:
        access = create_access_token(user_id, role)
        refresh = await self._refresh.issue(user_id)
        return TokenPair(access, refresh, get_settings().access_token_ttl)
