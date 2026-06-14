# Load & measurement harness

Measures live-delivery, read latency, throughput, and the single-instance
WebSocket connection ceiling (NFR-3, NFR-14). It does **not** assert thresholds —
v1.0 derives targets from these numbers (testing-strategy.md).

- `spectators.js` — k6 script: held WebSocket spectators + a paced scorer.
- `issue_target.py` — resolves the seeded match and mints a scorekeeper token.

## Run

Manually via the **Load (manual)** GitHub Action (a modest in-CI smoke), or point
it at any target:

    BASE_URL=https://<app> WS_URL=wss://<app> MATCH_ID=<id> TOKEN=<jwt> \
      VUS=500 DURATION=2m k6 run tests/load/spectators.js

The single-runner CI smoke can't prove the ~5,000 ceiling (app, database, and load
generator share one box); the real measurement is this same script pointed at the
deployment.
