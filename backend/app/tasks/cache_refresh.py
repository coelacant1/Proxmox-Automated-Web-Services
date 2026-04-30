"""Periodic cache refresh tasks - keep hot Redis keys warm so user requests rarely hit PVE."""

import asyncio
import logging

from celery import shared_task

from app.services.cache import cache_set

log = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _refresh_cluster_status_cache() -> dict:
    """Re-compute ``cluster_status`` for the primary cluster and push into Redis.

    This deliberately bypasses the normal lazy-cache read; we compute and then
    force-write the result so the next user request is guaranteed to hit a warm
    cache. Tolerant of PVE outages: failures are logged and surfaced in the
    payload but do not raise.
    """
    from app.routers.cluster import CLUSTER_STATUS_TTL_SECONDS, _compute_cluster_status
    from app.services.cluster_registry import NoClustersConfigured, cluster_registry

    if not cluster_registry.has_clusters():
        await cluster_registry.reload()

    if not cluster_registry.list_cluster_ids():
        return {"refreshed": [], "errors": []}

    try:
        payload = await _compute_cluster_status()
        await cache_set("cluster_status", payload, CLUSTER_STATUS_TTL_SECONDS)
        return {"refreshed": ["primary"], "errors": []}
    except NoClustersConfigured:
        return {"refreshed": [], "errors": []}
    except Exception as exc:
        log.warning("cluster_status refresh failed: %s", exc)
        return {"refreshed": [], "errors": ["primary"]}


@shared_task(name="paws.refresh_cluster_status_cache")
def refresh_cluster_status_cache():
    """Celery-scheduled entry point for cluster status cache warming."""
    return _run_async(_refresh_cluster_status_cache())


async def _refresh_vm_statuses_batch() -> dict:
    """Force-refresh the shared cluster_resources caches used by list pages.

    Beat runs this faster than the cache TTL so user requests almost always
    hit warm Redis and never block the event loop on a sync Proxmox call.
    """
    import asyncio as _asyncio

    from app.services.cache import cache_set
    from app.services.cluster_registry import NoClustersConfigured, cluster_registry
    from app.services.proxmox_cache import CLUSTER_RESOURCES_TTL, _resolve_cluster_id
    from app.services.proxmox_client import get_pve

    if not cluster_registry.has_clusters():
        await cluster_registry.reload()
    if not cluster_registry.has_clusters():
        return {"refreshed": False}

    try:
        pve = get_pve()
        cid = _resolve_cluster_id(None)
        all_resources = await _asyncio.to_thread(pve.get_cluster_resources, None)
        vm_resources = [r for r in all_resources if r.get("type") == "qemu"]
        await cache_set(f"pve:{cid}:cluster_resources:all", all_resources, CLUSTER_RESOURCES_TTL)
        await cache_set(f"pve:{cid}:cluster_resources:vm", vm_resources, CLUSTER_RESOURCES_TTL)
        return {"refreshed": True, "all": len(all_resources), "vm": len(vm_resources)}
    except NoClustersConfigured:
        return {"refreshed": False}
    except Exception as exc:
        log.warning("vm_statuses_batch refresh failed: %s", exc)
        return {"refreshed": False, "error": str(exc)}


@shared_task(name="paws.refresh_vm_statuses_batch")
def refresh_vm_statuses_batch():
    """Celery-scheduled entry point for batch VM status cache warming."""
    return _run_async(_refresh_vm_statuses_batch())
