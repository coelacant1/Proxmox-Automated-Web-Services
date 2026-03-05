"""Redis-backed rate limiting with sliding window."""

import time

import redis.asyncio as redis

from app.core.config import settings

_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
    """
    Sliding window rate limiter. Returns (allowed, remaining).
    """
    r = await get_redis()
    now = time.time()
    window_start = now - window_seconds
    pipe = r.pipeline()

    # Remove expired entries
    pipe.zremrangebyscore(key, 0, window_start)
    # Add current request
    pipe.zadd(key, {str(now): now})
    # Count requests in window
    pipe.zcard(key)
    # Set expiry on the key
    pipe.expire(key, window_seconds)

    results = await pipe.execute()
    request_count = results[2]
    remaining = max(0, max_requests - request_count)
    allowed = request_count <= max_requests

    return allowed, remaining


async def check_api_rate_limit(user_id: str) -> tuple[bool, int]:
    key = f"rate:api:{user_id}"
    return await check_rate_limit(key, settings.rate_limit_per_minute, 60)


async def check_action_rate_limit(user_id: str, action: str, max_per_hour: int) -> tuple[bool, int]:
    key = f"rate:action:{action}:{user_id}"
    return await check_rate_limit(key, max_per_hour, 3600)
