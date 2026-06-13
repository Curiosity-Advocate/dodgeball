"""Alembic environment — async engine, reads DATABASE_URL from app settings."""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

# The Alembic Config object (access to alembic.ini values).
config = context.config


def do_run_migrations(connection):
    """Called inside a sync context by run_sync; applies migrations."""
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect with an async engine and run migrations."""
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    """Emit raw SQL without connecting (used for --sql flag)."""
    url = get_settings().database_url
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())