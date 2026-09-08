"""In-memory fixed-window rate limiter (requirement N2).

Prototype-scoped: a single-process dict is fine for this assignment's runnable prototype.
A multi-instance deployment would need a shared store (e.g. Redis) instead -- called out in
docs/risks.md as a known limitation, not silently hidden.
"""
from __future__ import annotations

import time


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = self._hits.setdefault(key, [])
        cutoff = now - self.window_seconds
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True
