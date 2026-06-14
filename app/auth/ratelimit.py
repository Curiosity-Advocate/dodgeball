"""In-memory sliding-window rate limiter (NFR-12).

A process-local limiter for the auth endpoints, keyed by an arbitrary string
(e.g. "ip:1.2.3.4" or "acct:user@example.com"). Each key keeps the timestamps of
recent attempts and rejects once `max_attempts` fall within the trailing `window`.

Single-instance only (v1.0): counters live in this process and reset on restart.
A shared/Redis-backed limiter is the deferred horizontal-scaling step.
"""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Record an attempt for `key`; return True if allowed, False if it would
        exceed max_attempts within the trailing window. Rejected attempts are not
        recorded, so a key recovers once its earlier attempts age out.
        """
        now = time.monotonic()
        cutoff = now - self._window
        hits = self._hits[key]
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._max:
            return False
        hits.append(now)
        return True
