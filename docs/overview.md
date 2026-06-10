# DodgeballPlus — Design Narrative Overview

This document is the design walkthrough for the platform. It moves from the
problem, through how the work was decomposed, to the architecture that follows
and the boundaries of v1.0. Each section links to the deeper documents that
formalize it (requirements, architecture, decisions).

## 1. The Problem

Australian dodgeball — national and state competitions — has no real-time,
structured scoring layer. Scores are entered *after* matches into siloed league
platforms (Spawtz, PlayHQ); there is no live push to spectators, no way to follow
a match remotely as it happens, and standings appear only per-league, after the
fact. Spectators refresh pages; remote followers are blind.

The v1.0 MVP is a **live-scoring application**: an authorized scorekeeper
publishes scoring events *during* a match, and any number of spectators receive
those updates instantly — with a reliable reconnect flow so a dropped connection
never misses an update, and standings that recompute automatically. It is the
only live, push-based scoring layer the sport has.

The **authorized scorekeeper** is the primary actor the system is designed
around: they need a simple, reliable way to publish scoring events that reach
spectators immediately, with safe retries and no double-counting if their
connection drops. **Spectators** benefit by following live and remotely without
refreshing. The platform itself benefits too — the live event log becomes the
seed of a unified historical dataset in a later phase.

The headline engineering concern, therefore, is the **reliability of live
delivery**: completeness across disconnects (no missed updates) rather than raw
throughput. That single concern shapes most of the architecture that follows.

This is the v1.0 boundary. Historical scraping, identity resolution,
cross-competition rankings, and video-based game-state inference are explicitly
out of scope here and addressed in §8.

> Formalized in [requirements/functional.md](requirements/functional.md) and
> [requirements/non-functional.md](requirements/non-functional.md).

## 2. How the Problem Was Carved Up

Before choosing any technology, the problem is decomposed so that each concern can
be given the guarantees it actually needs. A live-scoring system mixes concerns
with genuinely different requirements: security-sensitive accounts, a
high-integrity write path, a high-fan-out delivery path, and simple reads.
Treating them uniformly leads to wrong decisions — one durability and consistency
policy applied everywhere over-protects data that is disposable while
under-protecting data that is irreplaceable. This decomposition is where the
data's real behaviour is made to drive the architecture, rather than a
one-size-fits-all default.

The solution uses two axes.

**Business areas** bound responsibilities and map onto module boundaries and the
API surface:

- **Identity & Access** — accounts, tokens, roles, and per-match scorekeeper
  assignment. Governs who may write.
- **Live Scoring** — the write path. The scorekeeper publishes scoring events,
  recorded in the event log as the source of truth.
- **Real-time Delivery** — fan-out of each event to subscribed spectators, plus
  the reconnect/replay flow that guarantees completeness.
- **Read & Query** — snapshots, event history, standings, and match listings.

**Data bands** classify data by how it behaves, which dictates how it is stored
and protected:

- **Append-only / immutable** — the event log (`match_events`). The single source
  of truth; never updated in place. Corrections are themselves new events.
- **Derived / recoverable** — projections (`match_state`, `standings`). A
  *projection* is a stored answer to a read question — the current score, or the
  league table — computed ("folded") from the events and rebuildable by replay,
  so losing one is cheap.
- **Slow / critical** — users and credentials. Low change rate, but high integrity
  and security requirements.

The decisive insight is the **intersection** of the two axes. Live Scoring writes
into the immutable band, which points to event sourcing (§3). Real-time Delivery
and Read & Query serve the derived band, so their data is projection-based and
cheap to lose. Identity sits in the slow/critical band, optimised for integrity
rather than speed. It is the *data-behaviour* axis that ultimately determines the
architecture.

**Why this decomposition.** Classifying by data behaviour surfaces a durability
*asymmetry* — only the event log must be truly durable, because every projection
can be recomputed — which tells us exactly where to concentrate high-availability
effort (§7). It aligns modules with the API, and it is forward-compatible: later
phases (historical scraping, video-derived game state) slot into the same bands
without reshaping the model.

Alternatives that were rejected:

- A **layer-only split** (controller / service / repository) organises code but
  says nothing about data guarantees; it would not have surfaced the durability
  asymmetry or the fit for event sourcing.
- An **entity-per-noun CRUD model** treats scoring as rows to update, missing that
  scoring is fundamentally an event *stream* and that reads are *derived* — the
  difference between a data platform and a glorified spreadsheet.
- A **single durability and consistency policy** for everything either
  over-protects disposable projections or under-protects the log.

> Formalized in [architecture/data-model.md](architecture/data-model.md).

## 3. Architectural Implications

The decomposition in §2 produces three architectural decisions that follow more
or less directly from it. They are stated here at a high level; each is argued in
full in its own Architecture Decision Record.

**Event sourcing.** Because the immutable band is the source of truth and every
read is derived, the write side is modelled as an append-only event log, and read
models are projections built from it. This gives a complete history and audit
trail for free, makes reliable reconnect possible (a client catches up by
replaying events), and turns score corrections into new events rather than lossy
overwrites; projections can always be rebuilt from the log. The cost is
conceptual weight — more to reason about than plain CRUD, and projections must be
kept rebuildable. The alternatives were rejected for concrete reasons: a
current-state-only CRUD model discards history and therefore cannot replay, which
would break the completeness guarantee that is the whole point of the system; a
CRUD model with a bolted-on audit log duplicates state and invites drift between
the two. See [decisions/0001-event-sourcing-for-live-scoring.md](decisions/0001-event-sourcing-for-live-scoring.md).

**Postgres as the event log.** The write path is low-volume and human-paced, but
it needs transactional appends, strict ordering, relational projections, and the
auth tables — ideally in one store that is simple to operate. PostgreSQL provides
all of this: transactions, an ordering column, the log and projections and
accounts in a single system, and replay as an ordinary query. It is not a
streaming broker, but at this write rate that capability is unnecessary.
Dedicated event-streaming systems (Kafka, EventStoreDB) were rejected as overkill
for the volume — they would still require a separate database for the relational
projections — and a NoSQL store was rejected because it cannot serve the
relational reads. The migration door is kept open through an `EventStore`
abstraction so the log can later move behind an outbox to Kafka without touching
call sites. See [decisions/0002-postgres-as-event-log.md](decisions/0002-postgres-as-event-log.md)
and [decisions/0003-eventstore-abstraction-for-kafka-portability.md](decisions/0003-eventstore-abstraction-for-kafka-portability.md).

**Stateless application, designed for horizontal extensibility.** Reliability of
live delivery is the headline concern, and the reconnect/replay model means the
application holds no irreplaceable in-memory state — the truth lives in the log.
That statelessness is deliberate: any instance can serve any request, a restart
loses nothing, and scaling horizontally becomes a low-friction future step
(`NFR-4`, `NFR-6`) rather than a redesign. v1.0 therefore commits to **no**
specific fan-out mechanism; a single instance with in-process fan-out is the only
delivery path, which is sufficient for the realistic scale (~5,000 concurrent
connections per `NFR-1`). The principle is to keep the design *extensible* to
horizontal scaling, not to build it now. A stateful, sticky-session design was
rejected because it couples clients to specific instances and is fragile across
restarts; building a distributed fan-out (e.g. a shared broker, or the specialist
live-gateway in [decisions/0009-fastapi-python-stack.md](decisions/0009-fastapi-python-stack.md))
up front was rejected as premature until measurement justifies it.

> The concrete shape these imply is described in §4; the data they operate on in §5.

## 4. The Shape of the System

v1.0 runs as **two containers**: a single **FastAPI application** (REST and
WebSocket in one process) and **PostgreSQL**.

```
        ┌───────────────────────────────────────────────┐
 write  │             FastAPI app (1 process)            │
 ──────▶│  • write API    scoring (authenticated)        │
 read   │  • read API     snapshot, replay, standings    │──▶ PostgreSQL
 ──────▶│  • WebSocket    live feed + reconnect/replay    │    event log +
   ws   │  • in-process fan-out                           │    projections +
 ──────▶│                                                │    accounts
        └───────────────────────────────────────────────┘
```

The application is a **modular monolith**: internally it is split into the
business areas from §2 (Identity & Access, Live Scoring, Real-time Delivery, Read
& Query) with clear module boundaries, but it ships as one deployable.
**PostgreSQL is the single integration point** — it holds the event log, the
projections, and the accounts, so there is no second datastore to keep
consistent. Fan-out to spectators happens **in-process** within the one instance,
which is sufficient for the realistic scale (~5,000 concurrent connections,
`NFR-1`).

This shape is chosen for operational simplicity: one language, one deployable,
the fewest moving parts, and a local stack of just the app plus Postgres
(`NFR-16`). Crucially, the statelessness from §3 means this simplicity costs
nothing in extensibility — because no irreplaceable state lives in the process,
the system can grow outward later without redesign.

**The future scaling path** (explicitly *not* built in v1.0, described here only
for context) is to split the monolith into independently scalable services — an
**API service**, a **WebSocket gateway** that holds the connections and fans out,
and a **worker** for background work such as projection rebuilds, standings
recomputation, and the later scraping and computer-vision jobs. Event sourcing
makes this split clean: each service coordinates through the event stream rather
than shared code, and the WebSocket gateway is exactly where the specialist
live-gateway from [decisions/0009-fastapi-python-stack.md](decisions/0009-fastapi-python-stack.md)
would slot in. This is pursued only when measurement (`NFR-3`) justifies it.

Two alternatives were rejected for v1.0. **Splitting into those separate services
now** was rejected as premature — it multiplies deploys, network hops, and
distributed-systems complexity to handle a load a single process serves
comfortably. A **sticky-session cluster** — pinning every viewer of a match to one
instance so it can broadcast locally without a shared bus — was rejected because
it binds state to a specific instance (fragile on restart), creates hot spots
(one popular match overloads a single instance with no way to rebalance), and
couples the write path to connection placement. The stateless design is the
deliberate opposite of stickiness.

> Detailed context and container diagrams: [architecture/c4-diagrams.md](architecture/c4-diagrams.md).

## 5. The Data the System Holds

All persistent state lives in PostgreSQL, organised by the data bands from §2.

**Append-only / immutable — the source of truth.**

- `match_events` — the event log. One row per scoring fact (`match_started`,
  `round_won_home`, `round_won_away`, `score_correction`, `match_finalized`),
  each carrying a per-match `version`, an `idempotency_key`, and the acting user.
  Rows are never updated or deleted; a correction is itself a new event.

**Derived / recoverable — projections.**

- `match_state` — the current score, round, and status of a match, plus the
  `version` it reflects. This is the snapshot a new viewer reads.
- `standings` — the within-competition points table.

Both are folded from `match_events` and can be rebuilt by replay, so they require
no special durability.

**Slow / critical — accounts.**

- `users` — accounts, roles, and hashed credentials.
- `refresh_tokens` — hashed, rotating refresh tokens, with reuse detection.

**Reference / domain — the nouns.**

- `competitions`, `teams`, `matches`, and `match_scorekeepers` (the
  single-scorekeeper-per-match assignment in v1.0).

**Conventions.**

- Events are immutable and append-only; corrections never overwrite.
- `version` is a per-match, contiguous, monotonic number. In v1.0 it serves a
  single purpose — the **ordering/replay cursor** that lets spectators detect gaps
  and reconnect without missing updates (`RT-2`, `RT-3`). In v2.0 it additionally
  becomes the optimistic-concurrency control for multiple scorekeepers (ADR-0004).
- Retries are made safe by a client-supplied `idempotency_key`, not by `version`.
- A projection stores the `version` it is current as of, so a snapshot is
  self-describing: state plus the cursor it corresponds to.
- All timestamps are stored in UTC.

> The full schema — columns, constraints, indexes — is in
> [architecture/data-model.md](architecture/data-model.md).

## 6. How Users Interact

The system is touched in three ways: a write path, a read path, and a live path.

**Write path — authenticated scoring (REST).** The assigned scorekeeper sends
scoring actions to `POST /matches/{id}/events` — starting a match, recording a
round result, issuing a correction, or finalising. The request is authenticated
with a JWT, authorised against the per-match assignment, and carries an
`idempotency_key` so a retry after a dropped response never double-counts.

**Read path — public reads (REST).** Anyone can fetch a match snapshot, replay a
match's events since a given version, read a competition's standings, and list or
filter matches. No account is required; this is the open, cacheable surface of
the system.

**Live path — WebSocket.** A spectator opens a connection to `WS /matches/{id}`
and is pushed each event in `version` order. On reconnect, the client resumes
from its last-seen version by replaying the events it missed, or — for an unknown
or very large gap — takes a fresh snapshot and continues from there. This path is
where the headline guarantee, completeness across disconnects (`NFR-5`), is
delivered.

Three rules cut across all three modes:

- **Auth asymmetry.** Writing requires a token *and* a per-match assignment;
  reading is open. The token guards who may change data, never who may see it.
- **Snapshot-then-stream.** A client first reads a snapshot (current state plus
  the `version` it corresponds to), then subscribes from that version — so it
  always knows exactly where it is in the stream.
- **Eventual consistency of standings.** Standings recompute when a match
  finalises, so immediately after a final whistle the competition table may lag
  the match's own state by a moment.

Two alternatives were considered and rejected. **Polling** instead of a WebSocket
for the live path was rejected as wasteful and unable to guarantee completeness
the way a version cursor plus replay can. **Putting reads behind authentication**
was rejected because public viewing is a deliberate design goal.

> The concrete endpoints, payloads, and status codes are specified in
> [architecture/api-contract.md](architecture/api-contract.md).

## 7. How the System Stays Healthy

The earlier sections describe the happy path; this one describes behaviour under
failure, and how the system is kept observable. Both follow from two earlier
decisions: the durability asymmetry (§2) and statelessness (§3).

**Durability where it matters.** Only `match_events` must be truly durable, so
high-availability effort is concentrated there: an HA PostgreSQL setup of primary,
replica, automatic failover, and backups (`NFR-8`). Projections need none of this
— if a projection is lost or corrupted, it is rebuilt by replaying the log. This
deliberate refusal to protect recomputable data is the payoff of the §2 carve-up.

**Failure handling.** One pattern recurs: the log is the truth, and everything
else recovers from it.

- An **app instance dies** — because instances are stateless, the load balancer
  routes around it; dropped WebSocket clients reconnect and replay (`NFR-6`).
- The **fan-out drops a message** — the transport is best-effort, so the client
  detects the `version` gap and recovers the missed events from the log (`NFR-7`).
- A **scorekeeper write times out** — it is retried with the same
  `idempotency_key`, so the action is never double-counted.
- A **Postgres node fails** — the replica is promoted; the small, durable log is
  intact and projections rebuild from it.

**Observability and measurement.** The system emits structured logs with trace IDs
and key metrics — events appended, active WebSocket connections, replay rate
(`NFR-14`). Beyond diagnosis, this is the data used to set concrete performance
targets later (`NFR-3`), which are deliberately left open for now.

**Housekeeping.** Routine maintenance — such as pruning expired and revoked
refresh tokens — and deployment of the app-plus-Postgres stack via Docker
(`NFR-16`) are operational concerns described in their own documents.

> Operational procedures: [operations/local-development.md](operations/local-development.md),
> [operations/deployment.md](operations/deployment.md), and
> [operations/scheduled-jobs.md](operations/scheduled-jobs.md).

## 8. What is Not in v1.0 and Why

The scope boundary is deliberate. Each exclusion below is left out for a reason,
not by omission.

**Feature deferrals.**

- **Multiple scorekeepers per match** → v2.0. The single-writer assumption is what
  lets `version` be a cursor only; supporting concurrent writers requires the
  optimistic-concurrency mechanism (ADR-0004).
- **Live game-state from video** (round count, players-per-side via computer
  vision) → v2.0. High value but high risk; it is gated behind a reliable
  human-scored core rather than depending on it.
- **Historical scraping** of league platforms (Spawtz, PlayHQ) → enrichment. The
  live event log is the priority; scraping is a separate ingestion concern layered
  on later.
- **Identity resolution / canonical de-duplication** → enrichment. Only needed
  once multiple data sources are unified.
- **Cross-competition rankings (Elo)** → enrichment. A richer projection over a
  larger dataset; v1.0 ships the simple within-competition points table.

**Infrastructure deferrals — built when measurement justifies them.**

- **Redis and horizontal scaling** → added only when measurement shows the single
  instance approaching its limits (`NFR-4`).
- **Kafka (via an outbox)** → added only when multiple independent consumers of the
  event stream exist (ADR-0003).
- **Concrete performance targets** → set from observed data (`NFR-3`), tracked as a
  Known Gap.

The throughline is to defer anything not required to prove the core live-scoring
loop, and to let *measurement* — not speculation — trigger each infrastructure
step.

> The sequenced plan across versions is in [roadmap.md](roadmap.md).
