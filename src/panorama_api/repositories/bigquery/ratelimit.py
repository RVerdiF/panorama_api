"""Rate limit em processo: 60 requisições por minuto por IP.

Sem Redis/Memorystore nesta fase (plano 2d §5). Janela deslizante por chave,
relógio injetável para teste determinístico e limite de chaves para não crescer
sem teto sob varredura de IPs.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

DEFAULT_LIMIT = 60
DEFAULT_WINDOW_S = 60.0
DEFAULT_MAX_KEYS = 10_000


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_s: float = 0.0


class InProcessRateLimiter:
    """Janela deslizante simples, thread-safe, sem dependência externa."""

    def __init__(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        window_s: float = DEFAULT_WINDOW_S,
        max_keys: int = DEFAULT_MAX_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit deve ser positivo")
        if window_s <= 0:
            raise ValueError("window_s deve ser positivo")
        self._limit = limit
        self._window_s = window_s
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = {}

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def window_s(self) -> float:
        return self._window_s

    def check(self, key: str) -> RateLimitDecision:
        now = self._clock()
        cutoff = now - self._window_s
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                retry_after = self._window_s - (now - bucket[0])
                return RateLimitDecision(False, 0, max(retry_after, 0.0))
            bucket.append(now)
            self._shrink_if_needed(now)
            return RateLimitDecision(True, self._limit - len(bucket))

    def _shrink_if_needed(self, now: float) -> None:
        if len(self._buckets) <= self._max_keys:
            return
        cutoff = now - self._window_s
        stale = [key for key, bucket in self._buckets.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            self._buckets.pop(key, None)
