"""Tiny JSON cache abstraction: Redis when REDIS_URL is set, otherwise in-process TTL dict."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from redis.asyncio import Redis


class Cache(Protocol):
    async def get_json(self, key: str) -> Any | None: ...
    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...


class InMemoryCache:
    def __init__(self, max_entries: int = 5_000) -> None:
        self._data: dict[str, tuple[float, str]] = {}
        self._max = max_entries

    async def get_json(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, raw = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        if len(self._data) >= self._max:
            now = time.monotonic()
            self._data = {k: v for k, v in self._data.items() if v[0] >= now}
            if len(self._data) >= self._max:
                self._data.pop(next(iter(self._data)))
        self._data[key] = (time.monotonic() + ttl_seconds, json.dumps(value, default=str))

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


class RedisCache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get_json(self, key: str) -> Any | None:
        raw = await self._redis.get(f"cache:{key}")
        return None if raw is None else json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self._redis.set(f"cache:{key}", json.dumps(value, default=str), ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._redis.delete(f"cache:{key}")
