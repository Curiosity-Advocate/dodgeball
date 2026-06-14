# Testing Strategy

The system makes strong correctness promises — no missed updates across a
disconnect (`NFR-5`), effectively-once application of events (`NFR-9`), and secure
token rotation (`NFR-11`). The strategy is to test those guarantees directly rather
than assume them, and to prioritise the reliability and security invariants over a
raw coverage percentage.

## Test levels

| Level | Owns | Verifies (examples) |
|-------|------|---------------------|
| **Unit** | Pure logic, no I/O | Projection folding (event → `match_state`), standings calculation, refresh-token rotation logic |
| **Integration** | Behaviour against a real PostgreSQL | `EventStore` append assigns the next `version`; a repeated `idempotency_key` returns the original event (`SCORE-6`); `UNIQUE` constraints hold; auth rotation + **reuse detection** |
| **API / contract** | HTTP behaviour from [api-contract.md](api-contract.md) | Status codes `201` / `200` / `403` / `404` / `422`; auth required on writes; reads public. (`409` is reserved for v2.0.) |
| **Real-time** | The reconnect guarantee | Disconnect mid-match and assert reconnect + replay loses **no** events (`NFR-5`); ordering and dedupe rules; snapshot-vs-replay selection |
| **Property / invariant** | Model-level truths | Replaying the log rebuilds the exact projection (`fold(log) == match_state`); a retried append never double-counts |
| **Architecture** | Module boundaries | The `import-linter` contracts from [module-boundaries.md](module-boundaries.md) run as tests and fail the build on a violating import |
| **Load & measurement** | Performance data (v1.0) | Live-delivery latency, read latency, throughput, and the concurrent-connection ceiling of a single instance, under many connections and a realistic event rate |

## Headline test — reconnect completeness

Because `NFR-5` is the headline guarantee, it gets a dedicated scenario: start a
match, stream events to a subscriber, force a disconnect after version *N*, continue
appending, then reconnect and assert the client converges to the exact final state
with every intermediate event accounted for — via both the replay path (small gap)
and the snapshot path (large/unknown gap).

## Load and measurement (part of v1.0)

Load and measurement are built and run **in v1.0**, not deferred. The harness drives
the system with many concurrent WebSocket connections and a realistic scoring-event
rate, recording live-delivery latency, read latency, throughput, and the
single-instance connection ceiling (`NFR-3`, `NFR-14`).

What v1.0 does **not** do is commit fixed pass/fail thresholds — those numbers are
*derived* from this measurement, which is precisely why the performance targets are
an open Known Gap rather than an invented constant. The same data also signals when
the deferred scaling lever (`NFR-4`) becomes necessary, so the measurement is what
makes the scale-out decision evidence-based instead of speculative.

## Test isolation

Database-backed tests share one `engine` fixture (`tests/conftest.py`) that
`TRUNCATE`s every domain table on entry, so each test starts from an empty
database. This holds for the real-time tests too, which need committed data —
the WebSocket route reads through its own connection. Pure unit tests request no
database fixture and never touch Postgres.

## Tooling

- `pytest` + `pytest-asyncio` for the suite.
- `hypothesis` for property-based tests of the pure projection logic.
- `httpx` ASGI client for API tests; Starlette's `TestClient` for the WebSocket tests.
- A real PostgreSQL, isolated per test by `TRUNCATE` (see Test isolation above).
- `import-linter` for the architecture contracts (run as a CI step).
- `k6` for the load & measurement harness, run non-gating in CI and against the deployment.

## Layout

```
tests/
├── unit/           pure logic + Hypothesis property tests (folding, standings, tokens)
├── integration/    EventStore + auth + read/write API against real Postgres
├── realtime/       reconnect / replay / ordering (Starlette WebSocket client)
└── load/           k6 concurrency + latency measurement harness
```

API contracts live in `integration/`; the architecture contracts run via
`import-linter` in CI rather than as a `tests/arch/` directory.
