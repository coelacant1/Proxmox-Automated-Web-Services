"""Redis-backed JSON cache with short TTLs.

Intended for memoizing expensive read-through calls (Proxmox API results,
computed aggregates) so hot endpoints can serve from cache and fall back to
the source on miss. Graceful on Redis outage: if Redis is unreachable the
cache becomes a no-op and callers hit the source directly.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.services.rate_limiter import get_redis

logger = logging.getLogger(__name__)

T = TypeVar("T")

_KEY_PREFIX = "paws:cache:"


async def cache_get(key: str) -> Any | None:
    """Return the cached JSON value for ``key`` or None on miss / error."""
    try:
        r = await get_redis()
        raw = await r.get(_KEY_PREFIX + key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.debug("cache_get(%s) failed: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    """Store ``value`` (must be JSON-serializable) under ``key`` for ``ttl_seconds``."""
    try:
        r = await get_redis()
        await r.set(_KEY_PREFIX + key, json.dumps(value), ex=max(1, ttl_seconds))
    except Exception as exc:
        logger.debug("cache_set(%s) failed: %s", key, exc)


async def cache_delete(key: str) -> None:
    """Remove a cached value if present. Safe on miss."""
    try:
        r = await get_redis()
        await r.delete(_KEY_PREFIX + key)
    except Exception as exc:
        logger.debug("cache_delete(%s) failed: %s", key, exc)


async def cached_call(key: str, ttl_seconds: int, producer: Callable[[], Awaitable[T]]) -> T:
    """Return the cached value, or call ``producer`` and cache its result.

    The producer is only awaited on cache miss. Exceptions propagate to the
    caller and are NOT cached (negative caching is opt-in via cache_set).
    """
    hit = await cache_get(key)
    if hit is not None:
        return hit  # type: ignore[return-value]
    value = await producer()
    await cache_set(key, value, ttl_seconds)
    return value


def now_epoch() -> int:
    """Integer UTC epoch seconds for ``cached_at`` stamps."""
    return int(time.time())
