"""Periodic cache refresh tasks - keep hot Redis keys warm so user requests rarely hit PVE."""

import asyncio
import logging

from celery import shared_task

log = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _refresh_cluster_status_cache() -> dict:
    """Re-compute ``cluster_status`` for every registered cluster and push into Redis.

    This deliberately bypasses the normal lazy-cache read; we compute and then
    force-write the result so the next user request is guaranteed to hit a warm
    cache. Tolerant of PVE outages: failures are logged and surfaced in the
    payload but do not raise.
    """
    from app.routers.cluster import CLUSTER_STATUS_TTL_SECONDS, _compute_cluster_status
    from app.services.cache import cache_set
    from app.services.cluster_registry import cluster_registry

    refreshed: list[str] = []
    errors: list[str] = []

    cluster_ids = cluster_registry.list_cluster_ids()
    if not cluster_ids:
        return {"refreshed": [], "errors": []}

    for cid in cluster_ids:
        try:
            payload = await _compute_cluster_status(cid)
            await cache_set(f"cluster_status:{cid}", payload, CLUSTER_STATUS_TTL_SECONDS)
            refreshed.append(cid)
        except Exception as exc:
            log.warning("cluster_status refresh failed for %s: %s", cid, exc)
            errors.append(cid)

    return {"refreshed": refreshed, "errors": errors}


@shared_task(name="paws.refresh_cluster_status_cache")
def refresh_cluster_status_cache():
    """Celery-scheduled entry point for cluster status cache warming."""
    return _run_async(_refresh_cluster_status_cache())
