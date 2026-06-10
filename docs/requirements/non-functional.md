# Non-Functional Requirements

> **Scope:** v1.0 live-scoring MVP. NFRs carry stable prefixed IDs; Architecture
> Decision Records cite them as drivers (e.g. *Driven by: `NFR-8`*).
>
> **Scale framing.** Realistic competitive-dodgeball viewership is niche — low
> thousands of concurrent viewers globally even for a World Championship final.
> (The widely-cited 123k-viewer "Creator Dodgeball" figure is a celebrity
> entertainment event, not the sport.) v1.0 therefore targets **~5,000 concurrent
> viewers on a single instance**, with horizontal scaling held back until
> measurement justifies it.

---

## Scalability

| ID | Requirement | Notes |
|----|-------------|-------|
| `NFR‑1` | Support a design target of **~5,000 concurrent spectator WebSocket connections on a single FastAPI instance**. | In-process fan-out in v1.0; one instance comfortably handles this range. |
| `NFR‑2` | A single Postgres primary handles all writes without sharding. | The write path (scoring) is human-paced and low-volume. |

## Performance & Scaling

> Measurement-driven. **No latency/throughput targets are committed in this
> document** — they will be set from real data per `NFR-3`.

| ID | Requirement | Notes |
|----|-------------|-------|
| `NFR‑3` | Instrument **live-delivery latency, read latency, event throughput, and concurrent connection count**, so concrete performance targets can be defined from real data. | Feeds off the observability instrumentation (`NFR-14`). |
| `NFR‑4` | **Deferred scaling lever:** introduce **Redis pub/sub + stateless horizontal instances** *only when* measurement shows the single instance approaching its limits. | Not built in v1.0. The statelessness in `NFR-6` makes this a low-friction addition. |

## Reliability & Availability

| ID | Requirement | Notes |
|----|-------------|-------|
| `NFR‑5` | **No update is ever lost across a client disconnect.** | Reconnect + replay from the durable log guarantees completeness. *(Headline guarantee.)* |
| `NFR‑6` | The application is **stateless**. | True even as a single instance — it is what makes adding instances (`NFR-4`) trivial; a restart loses no data because clients reconnect and replay. |
| `NFR‑7` | The fan-out transport is treated as **best-effort**. | In-process now, Redis later; the durable log backstops any dropped delivery, detected via version gaps. |

## Durability & Consistency

| ID | Requirement | Notes |
|----|-------------|-------|
| `NFR‑8` | The event log is durable. | HA Postgres: primary + replica + failover + backups. Projections (`match_state`, `standings`) are rebuildable from the log and need no special durability. |
| `NFR‑9` | Events are applied **effectively-once**. | v1.0: idempotency key (write-side) + client-side dedupe by version (read-side). The write-time version (optimistic-concurrency) check arrives in **v2.0** with multiple scorekeepers. |
| `NFR‑10` | Events are **immutable and append-only**. | Corrections are new events, never in-place updates. |

## Security

| ID | Requirement | Notes |
|----|-------------|-------|
| `NFR‑11` | Credentials and tokens are stored safely. | argon2id password hashing; signed access tokens; refresh tokens stored hashed, rotated on use, with reuse detection. |
| `NFR‑12` | Authentication endpoints are rate-limited. | Per IP and per account, against brute force. |
| `NFR‑13` | Only the assigned scorekeeper (or an admin) may write to a match. | Authorized at request time against the current assignment. |

## Observability

| ID | Requirement | Notes |
|----|-------------|-------|
| `NFR‑14` | Structured logging with request/trace IDs, plus key metrics. | Metrics: events appended, active WebSocket connections, replay rate. Provides the data for `NFR-3`. |

## Maintainability & Portability

| ID | Requirement | Notes |
|----|-------------|-------|
| `NFR‑15` | The event log is accessed **only through the `EventStore` abstraction**. | Keeps the Postgres → (outbox →) Kafka migration door open without touching call sites. |
| `NFR‑16` | The system runs locally via **Docker Compose**. | v1.0: app + Postgres. Redis is added only with the `NFR-4` scaling step. |

---

## Performance targets — to be defined

Concrete latency, throughput, and concurrency targets are **deliberately not set
in v1.0**. `NFR-3` requires the system to *measure* these first; targets will be
chosen from observed data and real concurrent-viewership numbers. Tracked as a
**Known Gap** in [roadmap.md](../roadmap.md).
