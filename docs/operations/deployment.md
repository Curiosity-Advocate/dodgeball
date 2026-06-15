# Deployment

The deployment target is **Render**. This documents how the application and database
run in production so deploys are reproducible and the environment is explicit.

> Describes the intended deployment. The referenced files (`Dockerfile`,
> `render.yaml`, CI workflow) are created in the build phase.

## Services

- **Web Service** — the FastAPI application, served by a **single `uvicorn`
  process** (one event loop, no worker fan-out). Auto-deploys from the Git
  repository.
- **Managed PostgreSQL (Neon)** — version 13+, hosted on Neon's free tier (Render's
  free tier allows only one database per account, kept for another project; the web
  service points at Neon via `DATABASE_URL`). `citext` is enabled once via a
  migration; `gen_random_uuid()` is built in (no extension needed).

Redis is not deployed in v1.0 (in-process fan-out, ADR-0006); it is added only with
the deferred scaling lever.

## Build and run

- A `Dockerfile` (or Render's native Python build) produces the app image.
- The start command runs a **single `uvicorn` process** (not multiple workers).
  This is a correctness constraint, not just a sizing choice: the live fan-out is an
  in-process pub/sub singleton (ADR-0006), so a second worker is a second process
  with its own dispatcher — an event published in one worker never reaches a
  subscriber held by another, and it fails silently (the event is still in the log,
  so only the live update is lost). Crossing processes is what Redis is for, and
  that is the deferred `NFR-4` lever. Until then: one process, one event loop. The
  load is I/O-bound (idle sockets parked on the event loop), not CPU-bound, so one
  process comfortably covers the v1.0 target.
- `DATABASE_URL` is injected from the Render PostgreSQL instance; other settings come
  from dashboard environment variables.

## Migrations

Migrations run from the container entrypoint (`docker-entrypoint.sh`): on start it
runs `alembic upgrade head`, then the idempotent `app.seed`, then execs `uvicorn`.
This is safe to run on every start because there is a single instance (no migration
race) and both steps are idempotent. The app only begins serving once the schema is
applied.

## Configuration

Configuration is declared in `render.yaml` (a Render Blueprint); secrets are never
committed:

- `DATABASE_URL` — the Neon connection string, set in the dashboard (`sync: false`).
  Neon hands it out as `postgres://…`; `app/core/config.py` normalizes the scheme to
  `postgresql+asyncpg://…` (the async driver the app and Alembic require).
- `JWT_SECRET` — generated per service by Render (`generateValue`), so a real signing
  key exists in production without committing one.
- `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL` — token lifetimes; default in config,
  overridable in the dashboard.

## API docs & CORS

FastAPI serves interactive API docs with no extra code: **Swagger UI at `/docs`** and
**ReDoc at `/redoc`**. With the demo seed always present, these are a live, clickable
reference. A bearer security scheme is declared so `/docs` has an **Authorize** button
for the write endpoints.

CORS is open in v1.0 (`allow_origins=["*"]`, no credentials): the API authenticates
with a bearer token in the `Authorization` header rather than cookies, so there is no
ambient credential for a cross-origin page to abuse. It is narrowed to specific client
origins once a browser client (e.g. the live-game overlay) ships.

## Durability

`NFR-8` sets the *target* posture for the durable data: a primary with a replica,
automatic failover, and backups. The key context is that this surface is **small** —
only `match_events` and the account tables must be durable; the projections
(`match_state`, `standings`) are rebuilt by replaying the log (the overview §2
durability asymmetry). That asymmetry makes strong durability cheap and lets it be
**dialled up in stages** rather than switched on all at once.

What v1.0 actually relies on:

- **Backups + point-in-time recovery (the baseline).** Render's managed Postgres
  takes automated backups and supports point-in-time recovery on its paid plans. This
  is the durability v1.0 depends on: if the database is lost or corrupted, it is
  restored to a chosen moment, and any projection drift is corrected by replay.
  Because the durable surface is small, the *recovery point* (how much data could be
  lost) is effectively the PITR granularity — acceptable for an MVP.

- **Read replica (enable when warranted).** A Render plan-tier feature that keeps a
  hot copy of the database — offloading reads and shortening recovery time. Not
  required for v1.0's load; enabled when read volume or a tighter recovery-time goal
  justifies it.

- **Automatic failover / HA (enable when warranted).** A higher-tier Render feature
  that promotes a standby automatically if the primary fails, minimising downtime.
  For an MVP the cost may not be justified — a restore-from-backup is an acceptable
  recovery *time* — so it is a deliberate later step, not a day-one default.

In short, v1.0 ships with **backups + PITR**, and moves up the ladder —
**replica → failover** — as the stakes grow. Because only the log and accounts need
protecting, each step is a Render plan choice, not a re-architecture. Exact backup
retention, PITR windows, and HA availability depend on the selected Render plan; see
Render's PostgreSQL documentation for current tiers.

## Scaling

v1.0 runs a single Web Service instance. Horizontal scaling — multiple stateless
instances plus Redis pub/sub for cross-instance fan-out — is the deferred lever
(`NFR-4`, ADR-0006), enabled on Render when measurement (`NFR-3`) shows it is needed.

## CI/CD

- Push to `main` triggers an auto-deploy on Render.
- GitHub Actions runs the test suite and the `import-linter` boundary checks before
  deploy, so a failing build does not ship.
