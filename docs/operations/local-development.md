# Local Development

How to run the system locally. The local environment mirrors the production target
(Render managed PostgreSQL 13+, with `citext` and `gen_random_uuid()`), so behaviour
matches what ships.

> This document describes the intended setup. The referenced files
> (`docker-compose.yml`, `.env.example`, command runner) are created in the build
> phase; this is the guide they fulfil.

## Stack

Two containers via Docker Compose:

- **`app`** — the FastAPI application, served by `uvicorn` with reload for
  development.
- **`postgres`** — PostgreSQL pinned to the same major version as the Render
  instance, with `citext` enabled.

Redis is **not** part of the local stack in v1.0 (fan-out is in-process, ADR-0006);
it is added only with the deferred scaling lever.

## Configuration

Copy `.env.example` to `.env` and adjust as needed. Expected variables:

- `DATABASE_URL` — connection string to the local Postgres.
- `JWT_SECRET` — signing key for access tokens.
- `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL` — token lifetimes.

Secrets are never committed; `.env.example` documents the keys with placeholder
values only.

## First run

1. `docker compose up` — starts Postgres and the app.
2. Apply the database schema / migrations (run on startup, or via the migrate
   command).
3. Run the seed script to create a demo competition, two teams, a match, and a
   scorekeeper account, so the live flow can be exercised immediately.

## Common commands

| Task | Command (intended) |
|------|--------------------|
| Start the stack | `docker compose up` |
| Apply migrations | `make migrate` |
| Seed demo data | `make seed` |
| Run tests | `pytest` (or `make test`) |
| Run the load/measurement harness | `make load` |
| Check module boundaries | `lint-imports` (import-linter) |

## Manual smoke test

A quick end-to-end check of the live loop:

1. `register` a user, then `login` to obtain tokens.
2. As admin, create a match and `PUT` the scorekeeper assignment.
3. Open a WebSocket to `WS /matches/{id}` in one terminal/tab.
4. `POST /matches/{id}/events` (e.g. `round_won_home`) as the scorekeeper.
5. Confirm the WebSocket receives the event with an incremented `version` and the
   updated state — and that a reconnect with a stale `last_version` replays the
   missed events.
