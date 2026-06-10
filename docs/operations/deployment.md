# Deployment

The deployment target is **Render**. This documents how the application and database
run in production so deploys are reproducible and the environment is explicit.

> Describes the intended deployment. The referenced files (`Dockerfile`,
> `render.yaml`, CI workflow) are created in the build phase.

## Services

- **Web Service** — the FastAPI application, served by `uvicorn` (behind
  `gunicorn` workers). Auto-deploys from the Git repository.
- **Render Managed PostgreSQL** — version 13+, with `citext` enabled once via a
  migration. `gen_random_uuid()` is built in (no extension needed).

Redis is not deployed in v1.0 (in-process fan-out, ADR-0006); it is added only with
the deferred scaling lever.

## Build and run

- A `Dockerfile` (or Render's native Python build) produces the app image.
- The start command runs `gunicorn` with `uvicorn` workers.
- `DATABASE_URL` is injected from the Render PostgreSQL instance; other settings come
  from dashboard environment variables.

## Migrations

Database migrations run on deploy via a release / pre-deploy command, so the schema
is applied before new application code serves traffic.

## Configuration

Environment variables are set in the Render dashboard and never committed:

- `DATABASE_URL` — from the Render PostgreSQL instance.
- `JWT_SECRET` — access-token signing key.
- `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL` — token lifetimes.

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
