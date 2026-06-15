from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://dodgeball:dodgeball@localhost:5432/dodgeball"
    jwt_secret: str = "dev-only-secret"
    access_token_ttl: int = 900  # seconds (15 minutes)
    refresh_token_ttl: int = 1209600  # seconds (14 days)
    auth_rate_limit_attempts: int = 10  # max auth attempts...
    auth_rate_limit_window: int = 60  # ...per this many seconds, per IP and per account

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg(cls, value: str) -> str:
        # Managed Postgres (Render/Neon) injects postgres:// or postgresql://; the app
        # and Alembic need the async driver.
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql://", 1)
        if value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
        # asyncpg rejects libpq-only query params (sslmode, channel_binding). When SSL
        # is requested (e.g. Neon's ?sslmode=require) collapse the query to the single
        # `ssl` arg asyncpg accepts; otherwise leave the URL as-is (e.g. local/CI).
        base, sep, query = value.partition("?")
        if sep and ("sslmode" in query or "ssl=" in query):
            value = f"{base}?ssl=require"
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
