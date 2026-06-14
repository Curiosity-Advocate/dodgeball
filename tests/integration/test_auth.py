"""Integration tests for the auth API — against a real Postgres.

The shared `engine` fixture (conftest) truncates the database per test, and the
rate limiter is overridden so it doesn't leak across tests.
"""

import uuid
from contextlib import asynccontextmanager

import httpx
import pytest
from httpx import ASGITransport

from app.api.deps import get_auth_service, get_rate_limiter
from app.api.main import create_app
from app.auth.ratelimit import RateLimiter
from app.auth.service import AuthService

_PW = "password123"


def _email() -> str:
    return f"{uuid.uuid4()}@authtest.local"


@asynccontextmanager
async def _client(engine, limiter):
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: AuthService(engine)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def client(engine):
    async with _client(engine, RateLimiter(10_000, 60)) as c:  # permissive by default
        yield c


async def _register(client, email):
    return await client.post(
        "/auth/register", json={"email": email, "password": _PW, "display_name": "T"}
    )


async def test_register_returns_user(client):
    email = _email()
    r = await _register(client, email)
    assert r.status_code == 201
    assert r.json()["user"]["email"] == email
    assert r.json()["user"]["role"] == "scorekeeper"


async def test_register_duplicate_email_409(client):
    email = _email()
    assert (await _register(client, email)).status_code == 201
    r = await _register(client, email)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


async def test_login_returns_tokens(client):
    email = _email()
    await _register(client, email)
    r = await client.post("/auth/login", json={"email": email, "password": _PW})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_login_wrong_password_401(client):
    email = _email()
    await _register(client, email)
    r = await client.post("/auth/login", json={"email": email, "password": "WRONG-pass"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


async def test_me_returns_current_user(client):
    email = _email()
    await _register(client, email)
    login = (await client.post("/auth/login", json={"email": email, "password": _PW})).json()
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {login['access_token']}"})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == email


async def test_me_without_token_401(client):
    assert (await client.get("/auth/me")).status_code == 401


async def test_refresh_rotates_token(client):
    email = _email()
    await _register(client, email)
    login = (await client.post("/auth/login", json={"email": email, "password": _PW})).json()
    r = await client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 200
    assert r.json()["refresh_token"] != login["refresh_token"]  # rotated


async def test_logout_then_refresh_rejected(client):
    email = _email()
    await _register(client, email)
    login = (await client.post("/auth/login", json={"email": email, "password": _PW})).json()
    rt = login["refresh_token"]
    assert (await client.post("/auth/logout", json={"refresh_token": rt})).status_code == 204
    assert (await client.post("/auth/refresh", json={"refresh_token": rt})).status_code == 401


async def test_refresh_reuse_revokes_chain(client):
    # Headline (NFR-11): reusing an already-rotated token revokes the whole chain.
    email = _email()
    await _register(client, email)
    login = (await client.post("/auth/login", json={"email": email, "password": _PW})).json()
    token_a = login["refresh_token"]

    rotated = (await client.post("/auth/refresh", json={"refresh_token": token_a})).json()
    token_b = rotated["refresh_token"]  # A -> B, B is now the active token

    reuse = await client.post("/auth/refresh", json={"refresh_token": token_a})  # reuse A
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "token_reused"

    # The active descendant B must also be dead now — the chain was revoked.
    assert (await client.post("/auth/refresh", json={"refresh_token": token_b})).status_code == 401


async def test_rate_limit_returns_429(engine):
    async with _client(engine, RateLimiter(max_attempts=2, window_seconds=60)) as c:
        results = [(await _register(c, _email())).status_code for _ in range(3)]
    assert results == [201, 201, 429]
