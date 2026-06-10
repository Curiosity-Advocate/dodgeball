# DodgeballPlus — Roadmap

This document sequences development into version-themed milestones, with explicit
boundaries between what is done, what is next, and what is deferred. Each version
resolves a coherent theme rather than a grab-bag of features. It is the single
referenced home for the scope decisions made in [overview.md](overview.md) §8.

---

## v1.0 — Live Scoring MVP (Current)

**Goal:** prove the core loop — score a match live, deliver every update reliably,
and recompute standings — with no missed updates across disconnects.

**Implemented.**

- Identity & access: registration, login, refresh-token rotation, logout, RBAC,
  single-scorekeeper-per-match assignment (`AUTH-*`).
- Live scoring: start, round results, corrections, finalisation, with idempotent
  appends (`SCORE-*`).
- Real-time delivery: WebSocket live feed, ordered by `version`, with
  snapshot-and-replay reconnect (`RT-*`).
- Read & query: snapshot, event replay, standings, match listings (`READ-*`).
- Event-sourced log (`match_events`) with `match_state` and `standings`
  projections.
- Load & measurement harness for live-delivery latency, throughput, and
  concurrent connections (`NFR-3`).

**Known gaps.**

- Concrete performance targets (live-delivery latency, read latency, throughput)
  are deliberately unset; they will be chosen from measured data (`NFR-3`).

---

## v2.0 — Historical Data Platform & Multi-scorekeeper

**Goal:** widen the platform from a single live match to a body of historical data,
and allow more than one scorekeeper per match.

- **Multiple scorekeepers per match.** Introduces write-time optimistic concurrency
  via `version` (`expected_version` check, 409-and-retry) to serialise concurrent
  writers (ADR-0004).
- **Historical scraping.** Ingest results from league platforms (Spawtz, PlayHQ)
  into the same data model.
- **Identity resolution.** Canonical de-duplication of teams, clubs, and players
  across sources, so scattered records resolve to one entity.
- **Cross-competition rankings.** An Elo-style projection over the unified
  dataset — a single rating that no per-league table can produce.

These four are grouped together because they are interdependent: identity
resolution and cross-competition rankings only have meaning once scraping has
unified multiple sources.

---

## v3.0 — Live Game ML (Computer Vision)

**Goal:** derive live game-state directly from match video, for streams that carry
no structured score feed.

- Video-derived **round count** and **players-per-side** (e.g. 3-vs-2).
- Fisheye court calibration (undistort → homography → zone classification) plus
  player detection (YOLO).
- The human-scored core from v1.0 remains the source of truth; the ML output is an
  assistive, clearly-labelled estimate, not a dependency.

This is the highest-risk phase and is sequenced last for that reason.

---

## Scaling Milestones (cross-cutting, measurement-triggered)

These are not bound to a version. Each is built only when measurement shows it is
needed, per the design philosophy below.

- **Redis pub/sub + stateless horizontal instances** — added when a single
  instance approaches its connection limit (`NFR-4`).
- **Kafka via a transactional outbox** — added when multiple independent consumers
  of the event stream exist (ADR-0003). Postgres remains the authoritative
  write-side.

---

## Permanently Out of Scope

These are rejected, not merely deferred.

- **Ingesting third-party video without consent.** Live video is taken only via a
  direct feed or partnership, never by pulling someone else's stream — a legal and
  platform-terms boundary.
- **Pure-gameplay score inference with no structured signal.** Reconstructing the
  score by watching gameplay alone (tracking eliminations frame-by-frame) is
  research-grade and unreliable; the v3.0 approach counts rounds and players from
  bounded signals instead.

---

## Design Philosophy

The event log is the spine: every later phase — scraping, rankings, video — attaches
to it rather than reshaping it. Scope is deferred until a feature is actually needed,
and infrastructure steps (Redis, Kafka, horizontal scaling) are triggered by
measurement rather than speculation. Each version resolves dependencies in order
instead of introducing unrelated scope.
