FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /code

# Dependency layer first so it caches independently of code changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app

CMD ["uv", "run", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
