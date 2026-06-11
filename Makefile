.PHONY: up test lint migrate seed

up:
	docker compose up

test:
	uv run pytest

lint:
	uv run ruff check app tests
	uv run ruff format --check app tests
	uv run lint-imports

migrate: # wired up in Phase 1
	uv run alembic upgrade head

seed: # wired up in Phase 1
	@echo "seed script arrives in Phase 1"
