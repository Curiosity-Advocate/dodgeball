from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://dodgeball:dodgeball@localhost:5432/dodgeball"
    jwt_secret: str = "dev-only-secret"
    access_token_ttl: int = 900  # seconds (15 minutes)
    refresh_token_ttl: int = 1209600  # seconds (14 days)
    auth_rate_limit_attempts: int = 10  # max auth attempts...
    auth_rate_limit_window: int = 60  # ...per this many seconds, per IP and per account


@lru_cache
def get_settings() -> Settings:
    return Settings()
