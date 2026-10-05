"""Fixed-window rate limiter with a Redis backend and an in-memory fallback."""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

from redis.asyncio import Redis


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Register one hit. Returns ``(allowed, retry_after_seconds)``."""
        ...

    async def reset(self) -> None: ...


class InMemoryRateLimiter:
    """Process-local limiter. Correct for a single instance; use Redis when scaling out."""

    def __init__(self) -> None:
        self._windows: dict[str, tuple[int, int]] = {}  # key -> (window_start, count)
        self._lock = asyncio.Lock()

    async def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        async with self._lock:
            start, count = self._windows.get(key, (window_start, 0))
            if start != window_start:
                start, count = window_start, 0
            count += 1
            self._windows[key] = (start, count)
            if len(self._windows) > 10_000:  # bound memory: drop stale windows
                self._windows = {k: v for k, v in self._windows.items() if v[0] == window_start}
        retry_after = start + window_seconds - now
        return count <= limit, max(retry_after, 1)

    async def reset(self) -> None:
        self._windows.clear()


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        redis_key = f"rl:{key}:{window_start}"
        pipe = self._redis.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds + 1)
        count, _ = await pipe.execute()
        retry_after = window_start + window_seconds - now
        return int(count) <= limit, max(retry_after, 1)

    async def reset(self) -> None:  # pragma: no cover - only used by tests on the memory backend
        async for key in self._redis.scan_iter("rl:*"):
            await self._redis.delete(key)
