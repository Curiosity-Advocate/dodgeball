"""Auth HTTP router: register, login, refresh, logout, me (api-contract.md)."""

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_auth_service, get_current_user, get_rate_limiter
from app.auth.errors import RateLimited
from app.auth.ratelimit import RateLimiter
from app.auth.service import AuthService, TokenPair, User
from app.auth.tokens import AccessTokenClaims

router = APIRouter(prefix="/auth", tags=["auth"])


# ---- request/response schemas (wire format, distinct from domain types) ----


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "new.user@example.com",
                "password": "password123",
                "display_name": "New User",
            }
        }
    )

    email: str
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1)


class LoginRequest(BaseModel):
    # The seeded demo account, so "Try it out" logs in against fresh data out of the box.
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "scorekeeper@demo.local", "password": "demo-password"}
        }
    )

    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: str

    @classmethod
    def of(cls, user: User) -> "UserResponse":
        return cls(id=user.id, email=user.email, display_name=user.display_name, role=user.role)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

    @classmethod
    def of(cls, pair: TokenPair) -> "TokenResponse":
        return cls(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
        )


def _client_ip(request: Request) -> str:
    # Behind Render's proxy the real client is the left-most X-Forwarded-For entry;
    # fall back to the direct peer for local/dev. Trusted only because the app is
    # reachable solely through the proxy.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> dict:
    if not limiter.allow(f"ip:{_client_ip(request)}"):
        raise RateLimited()
    user = await service.register(body.email, body.password, body.display_name)
    return {"user": UserResponse.of(user).model_dump()}


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> TokenResponse:
    ip = _client_ip(request)
    if not limiter.allow(f"ip:{ip}") or not limiter.allow(f"acct:{body.email.lower()}"):
        raise RateLimited()
    return TokenResponse.of(await service.login(body.email, body.password))


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> TokenResponse:
    if not limiter.allow(f"ip:{_client_ip(request)}"):
        raise RateLimited()
    return TokenResponse.of(await service.refresh(body.refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.logout(body.refresh_token)


@router.get("/me")
async def me(
    claims: AccessTokenClaims = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> dict:
    return {"user": UserResponse.of(await service.get_user(claims.user_id)).model_dump()}
