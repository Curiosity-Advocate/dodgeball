# ADR-0006 — In-process fan-out now, Redis when measured

> **Context:** Expands overview.md §3–4. Driven by: `NFR-1`, `NFR-4`, `NFR-7`.

**Status:** Accepted. Adopted in v1.0.

---

## Context

Real-time delivery must push each appended event to every spectator subscribed to
that match. With several server instances, subscribers for one match are spread
across them and a cross-instance message bus (e.g. Redis pub/sub) is required to
reach them all. But realistic competitive-dodgeball viewership is low thousands of
concurrent connections even at a global final, and a single instance comfortably
holds the ~5,000-connection design target (`NFR-1`).

## Decision

v1.0 runs a **single instance with in-process fan-out**: an appended event is
pushed directly to the local WebSocket subscribers. **Redis pub/sub plus stateless
horizontal instances is deferred** and introduced only when measurement (`NFR-3`)
shows the single instance approaching its limits (`NFR-4`). At any scale the fan-out
transport is treated as best-effort, with the durable log backstopping dropped
deliveries via version-gap recovery (`NFR-7`).

## Consequences

**Positive.**

- Simplest possible operation — no broker to run; local stack is app + Postgres
  (`NFR-16`).
- Statelessness keeps the eventual scale-out a low-friction addition rather than a
  redesign.
- Avoids building and paying for distributed infrastructure before it is justified.

**Negative.**

- A single instance is a single point of failure for *liveness* until scaled — but
  the durable log means no data is lost, and clients reconnect and replay.
- Cross-instance fan-out remains deferred work for when scale arrives.

## Alternatives considered

- **Build Redis + multiple instances now.** Premature for the realistic load;
  multiplies operational surface to solve a problem not yet measured (`NFR-4`).
- **Sticky-session cluster.** Pinning a match's viewers to one instance avoids a
  bus but binds state to an instance (fragile on restart) and creates hot spots
  (overview §4).
- **Managed pub/sub (Ably, Pusher).** Removes the operational burden but adds cost
  and lock-in, and demonstrates less of the mechanism.
