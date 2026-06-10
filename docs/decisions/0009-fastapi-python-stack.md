# ADR-0009 — Python + FastAPI as the core stack

> **Context:** Informs overview.md §3–4. Driven by: `NFR-1`, `NFR-15`, and the v2.0 video-CV phase (roadmap).

**Status:** Accepted. Adopted in v1.0.

---

## Context

The language/framework for the core service was an open decision, not a given. The
system has a real-time delivery requirement (`RT-*`, ~5,000 concurrent connections
per `NFR-1`), an event-sourcing model over Postgres (`NFR-8`, `NFR-15`), a
horizontal-extensibility goal (`NFR-4`, `NFR-6`), and a later v2.0 phase that adds
**computer-vision / ML** work plus historical **scraping** (roadmap).

Six candidates were evaluated against those drivers: Python + FastAPI, Java + Spring
Boot, Node.js + NestJS, Go, Elixir + Phoenix, and C#/.NET + SignalR. They split into
a **core list** (my familiar languages: Java, Python, Node — in that order
of experience) and **real-time specialists** (Elixir, Go, .NET).

## Decision

Adopt **Python + FastAPI** as the core service, with **PostgreSQL** and
**SQLAlchemy/Alembic**. The choice followed a three-step process:

1. **Global optimum for real-time fan-out — Elixir/Phoenix (Go second).** Phoenix is
   purpose-built for this: a lightweight process per connection and a runtime that
   *clusters across instances natively* (cross-instance fan-out with no external
   broker). However, both Elixir and Go are weak for the v2.0 CV/ML phase, so neither
   is a candidate to build the *whole* system in.

2. **Core optimum — Python (over Java and Node).** Python is the only core option
   that does CV/ML **and** scraping natively, avoiding a second language later. It
   also offers fast deployment. Its real-time
   throughput is adequate for the ~5,000-connection target on a single instance.
   Java was the strongest *v1.0-only* option but imposes a
   two-language cost once the CV phase arrives; Node is the least familiar core and
   also CV-weak.

3. **Integration / extension path.** Event sourcing makes the real-time tier
   separable: because the write side only *appends to the durable log*, a specialist
   **live-gateway service (Elixir/Phoenix or Go)** can later subscribe to the event
   stream and take over fan-out at scale. The boundary is a language-agnostic event
   stream, not shared code, so the core's choice does not foreclose the global
   optimum — it defers it.

## Consequences

**Positive.**

- One language spans all three phases (live scoring, scraping, CV/ML) — no
  second runtime to learn or operate for the roadmap.
- Fast iteration and deployment; light operational footprint (`NFR-16`).
- ~5,000 concurrent connections is comfortable on a single FastAPI instance, so no
  distributed infrastructure is needed for v1.0.
- The specialist-extraction path (Phoenix/Go live-gateway) remains open and clean,
  preserving the global optimum as a measured, future step rather than a rewrite.

**Negative.**

- Python's real-time ceiling per instance is lower than Elixir/Go. Mitigated by the
  documented extension path and by the realistic scale (`NFR-1`).
- The GIL limits CPU parallelism; irrelevant for our I/O-bound WebSocket fan-out, but
  noted so future CPU-heavy work (e.g. CV) is run out-of-process / in workers.

## Alternatives considered

- **Java + Spring Boot.** excellent event-sourcing and
  transaction tooling; virtual threads make ~5k connections comfortable. Dismissed as
  the *core* because it forces a second language (Python) for the v2.0 CV phase.
- **Node.js + NestJS.** Strong at many connections; Playwright is excellent for the
  JS-rendered Spawtz scraping. Weak for CV/ML.
- **Elixir + Phoenix.** The global optimum for real-time fan-out, retained as the
  preferred **extension path**. Dismissed as the whole-system language: no ML
  ecosystem and unfamiliar.
- **Go.** Excellent concurrency/performance and very marketable. Dismissed for the
  same CV-ecosystem gap and unfamiliarity; second choice for the live-gateway.
- **C#/.NET + SignalR.** Mature real-time story and a first-class Postgres event
  store (Marten). Dismissed — unfamiliar and CV-weak.
