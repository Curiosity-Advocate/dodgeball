# DodgeballPlus — Documentation

> *Live dodgeball scoring — plus free analytics.*

A live-scoring data platform for Australian dodgeball: an authorised scorekeeper
publishes scoring events during a match, any number of spectators receive updates
instantly over WebSocket with a reliable reconnect flow, and standings recompute
automatically. Built on an event-sourced log as the single source of truth.

**Start here:** [overview.md](overview.md) — the design narrative end to end.

## Suggested reading order

1. [overview.md](overview.md) — problem, decomposition, architecture, scope.
2. [requirements/](requirements/) — what the system must do, and its qualities.
3. [architecture/](architecture/) — the concrete design.
4. [decisions/](decisions/) — why each key choice was made.
5. [operations/](operations/) — how to run and deploy it.
6. [roadmap.md](roadmap.md) — what is built now and what comes next.

## Documents

### Root

| Document | Purpose |
|----------|---------|
| [overview.md](overview.md) | Design narrative in eight sections |
| [roadmap.md](roadmap.md) | Version-themed plan (v1.0 → v2.0 → v3.0) |

### Requirements

| Document | Purpose |
|----------|---------|
| [requirements/functional.md](requirements/functional.md) | Functional requirements (`AUTH`, `SCORE`, `RT`, `READ`) |
| [requirements/non-functional.md](requirements/non-functional.md) | Non-functional requirements (`NFR-*`) |

### Architecture

| Document | Purpose |
|----------|---------|
| [architecture/data-model.md](architecture/data-model.md) | Schema (DDL) — event log, projections, accounts |
| [architecture/api-contract.md](architecture/api-contract.md) | REST + WebSocket contract |
| [architecture/c4-diagrams.md](architecture/c4-diagrams.md) | Context, container, component, future-state diagrams |
| [architecture/module-boundaries.md](architecture/module-boundaries.md) | Modules and dependency rules |
| [architecture/testing-strategy.md](architecture/testing-strategy.md) | Test levels and the reliability guarantees they verify |

### Decisions (ADRs)

| ADR | Decision |
|-----|----------|
| [0001](decisions/0001-event-sourcing-for-live-scoring.md) | Event sourcing for live scoring |
| [0002](decisions/0002-postgres-as-event-log.md) | PostgreSQL as the event log |
| [0003](decisions/0003-eventstore-abstraction-for-kafka-portability.md) | `EventStore` abstraction for Kafka portability |
| [0004](decisions/0004-optimistic-concurrency-per-match-version.md) | Optimistic concurrency via per-match version (v2.0) |
| [0005](decisions/0005-idempotency-key-on-event-append.md) | Idempotency key on event append |
| [0006](decisions/0006-in-process-fanout-redis-when-measured.md) | In-process fan-out now, Redis when measured |
| [0007](decisions/0007-jwt-access-plus-refresh-rotation.md) | JWT access token + refresh-token rotation |
| [0008](decisions/0008-per-match-authorization-outside-token.md) | Per-match authorisation outside the token |
| [0009](decisions/0009-fastapi-python-stack.md) | Python + FastAPI as the core stack |
| [0010](decisions/0010-snapshot-plus-replay-reconnect.md) | Snapshot + replay reconnect |

### Operations

| Document | Purpose |
|----------|---------|
| [operations/local-development.md](operations/local-development.md) | Running the system locally |
| [operations/deployment.md](operations/deployment.md) | Deploying to Render |
| [operations/scheduled-jobs.md](operations/scheduled-jobs.md) | Scheduled and on-demand background work |
