# Scheduled Jobs

By design, v1.0 has very little scheduled work: the core is event-driven, so most
"keep things current" behaviour happens in response to events rather than on a timer.
This document lists what actually runs on a schedule, what deliberately does not, and
where future jobs will land.

> Describes the intended jobs. The commands and schedule configuration are created in
> the build phase.

## Scheduled

- **Refresh-token pruning.** Periodically delete expired and revoked refresh tokens
  so the `refresh_tokens` table does not grow without bound. The job is naturally
  idempotent (deleting already-absent rows is a no-op) and safe to run repeatedly.
  Implemented as a **Render Cron Job** (or an in-process scheduler) invoking a
  management command, on a daily cadence.

## Not scheduled (clarified to avoid confusion)

- **Standings recomputation is event-driven, not a cron job.** It runs when a match
  finalises (`match_finalised` → `RT-5`), not on a timer.
- **Projection rebuild is an on-demand maintenance utility, not a schedule.** If a
  projection (`match_state`, `standings`) is ever lost or corrupted, it is rebuilt by
  replaying `match_events` via a manually-run command. It exists because projections
  are recomputable (ADR-0001), not because they need periodic refreshing.

## Future (not v1.0)

- **Scraping ingestion** jobs arrive in v2.0 (historical data platform) and will be
  genuine scheduled work — polling league sources on a cadence.
- The **load / measurement harness** runs on demand or in CI, not as a production
  cron job.
