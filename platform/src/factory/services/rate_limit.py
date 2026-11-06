"""A per-principal token bucket for tool calls (plan ruling 4). In memory: a restart refills it.

Invariants:
- `allow` spends one token or refuses; it never blocks. The bucket holds at most `burst` tokens and
  refills at `rate` per second of the injected clock.
- Principals do not share a bucket. Safe to call from several worker threads.
"""

import threading
from collections.abc import Callable

DEFAULT_RATE = 20.0
DEFAULT_BURST = 100


class RateLimiter:
    def __init__(self, rate: float, burst: int, clock: Callable[[], float]) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("rate must be positive and burst at least 1")
        self._rate = rate
        self._burst = burst
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, principal: str) -> bool:
        now = self._clock()
        with self._lock:
            tokens, then = self._buckets.get(principal, (float(self._burst), now))
            tokens = min(float(self._burst), tokens + max(0.0, now - then) * self._rate)
            allowed = tokens >= 1.0
            self._buckets[principal] = (tokens - 1.0 if allowed else tokens, now)
            return allowed
