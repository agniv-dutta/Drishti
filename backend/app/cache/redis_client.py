"""Async cache facade: Redis when available, in-memory fallback otherwise.

Used for ML model artifacts, hot session data and rate counters. The fallback
keeps local dev and CI dependency-free.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from app.core.config import get_settings


class _MemoryCache:
    """Minimal TTL cache standing in for Redis."""

    def __init__(self) -> None:
        self._store: Dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at and expires_at < time.monotonic():
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        async with self._lock:
            expires_at = time.monotonic() + ttl if ttl else 0
            self._store[key] = (expires_at, value)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def ping(self) -> bool:
        return True

    @property
    def backend(self) -> str:
        return "memory"


class _RedisCache:
    def __init__(self, client) -> None:
        self._client = client

    async def get(self, key: str) -> Optional[str]:
        value = await self._client.get(key)
        return None if value is None else str(value)

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        await self._client.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    @property
    def backend(self) -> str:
        return "redis"


class CacheClient:
    """Public API over whichever backend is active."""

    def __init__(self, backend) -> None:
        self._backend = backend

    @property
    def backend_name(self) -> str:
        return self._backend.backend

    async def ping(self) -> bool:
        try:
            return await self._backend.ping()
        except Exception:
            return False

    async def get_raw(self, key: str) -> Optional[str]:
        return await self._backend.get(key)

    async def set_raw(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        await self._backend.set(key, value, ttl or default_ttl())

    async def delete(self, key: str) -> None:
        await self._backend.delete(key)

    # ---- JSON convenience -------------------------------------------------
    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.get_raw(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            await self.delete(key)
            return None

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        await self.set_raw(key, json.dumps(value, default=str), ttl)

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        ttl: Optional[int] = None,
    ) -> Any:
        cached = await self.get_json(key)
        if cached is not None:
            return cached
        fresh = await factory()
        await self.set_json(key, fresh, ttl)
        return fresh


_cache: Optional[CacheClient] = None
_init_lock = asyncio.Lock()


def default_ttl() -> int:
    return get_settings().cache_ttl_seconds


async def get_cache() -> CacheClient:
    """Singleton cache client; falls back to memory when Redis is absent/down."""
    global _cache
    if _cache is not None:
        return _cache
    async with _init_lock:
        if _cache is not None:
            return _cache
        settings = get_settings()
        backend = None
        if settings.redis_url:
            try:
                import redis.asyncio as aioredis

                client = aioredis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1.5,
                )
                await client.ping()
                backend = _RedisCache(client)
            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                from app.core.logging_config import get_logger

                get_logger("drishti.cache").warning(
                    "cache.redis_unreachable_fallback_memory", error=str(exc)
                )
        if backend is None:
            backend = _MemoryCache()
        _cache = CacheClient(backend)
        return _cache
