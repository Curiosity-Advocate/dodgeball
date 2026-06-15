#!/bin/sh
set -e

# Single instance, so no migration race: apply schema, idempotently seed, then serve.
alembic upgrade head
python -m app.seed

exec uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
