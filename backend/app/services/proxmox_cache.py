"""Async + Redis-cached wrappers around the synchronous proxmoxer client.

The proxmoxer library is built on `requests` (sync). Calling it directly inside
a FastAPI ``async def`` handler blocks the entire event loop for the duration
of the HTTPS round-trip to Proxmox (~200 ms - 2 s each), which serializes ALL
concurrent requests including pure-DB endpoints like ``/quota``.

Every router that needs Proxmox data on the request path should go through
this module. It does two things:

1. Wraps the sync call in :func:`asyncio.to_thread` so the event loop stays
   responsive.
2. Caches the result in Redis with a short TTL so back-to-back page loads do
   not all hit Proxmox.

Hot reads also have Celery beat warmers in :mod:`app.tasks.cache_refresh` so
the first user request after a cache expiry typically still hits a warm key.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.cache import cached_call
from app.services.cluster_registry import NoClustersConfigured, cluster_registry
from app.services.proxmox_client import get_pve

logger = logging.getLogger(__name__)


CLUSTER_RESOURCES_TTL = 15
NODES_TTL = 15
CLUSTER_STATUS_TTL = 15
TEMPLATES_TTL = 60
STORAGE_LIST_TTL = 60
SDN_ZONES_TTL = 60
SDN_VNETS_TTL = 30


def _resolve_cluster_id(cluster_id: str | None) -> str:
    """Return the resolved cluster id for cache keying. Falls back to 'default'."""
    if cluster_id:
        return cluster_id
    try:
        return cluster_registry.default_cluster or "default"
    except NoClustersConfigured:
        return "default"


async def get_cluster_resources(cluster_id: str | None = None, resource_type: str | None = None) -> list[dict]:
    """Cached + async wrapper around ``pve.get_cluster_resources``.

    Returns ``[]`` on Proxmox failure or no clusters configured (callers should
    treat as "live data unavailable" rather than fatal error).
    """
    cid = _resolve_cluster_id(cluster_id)
    key = f"pve:{cid}:cluster_resources:{resource_type or 'all'}"

    async def _produce() -> list[dict]:
        try:
            pve = get_pve(cluster_id)
            return await asyncio.to_thread(pve.get_cluster_resources, resource_type)
        except NoClustersConfigured:
            return []
        except Exception as exc:
            logger.warning("get_cluster_resources(%s, %s) failed: %s", cid, resource_type, exc)
            return []

    return await cached_call(key, CLUSTER_RESOURCES_TTL, _produce)


async def get_vm_status_map(cluster_id: str | None = None) -> dict[int, dict]:
    """Return a vmid -> status dict for all VMs/LXCs in the cluster.

    Backed by :func:`get_cluster_resources` so it shares its cache.
    """
    resources = await get_cluster_resources(cluster_id)
    return {r["vmid"]: r for r in resources if r.get("vmid") and r.get("type") in ("qemu", "lxc")}


async def get_nodes(cluster_id: str | None = None) -> list[dict]:
    cid = _resolve_cluster_id(cluster_id)
    key = f"pve:{cid}:nodes"

    async def _produce() -> list[dict]:
        try:
            pve = get_pve(cluster_id)
            return await asyncio.to_thread(pve.get_nodes)
        except NoClustersConfigured:
            return []
        except Exception as exc:
            logger.warning("get_nodes(%s) failed: %s", cid, exc)
            return []

    return await cached_call(key, NODES_TTL, _produce)


async def get_cluster_status(cluster_id: str | None = None) -> list[dict]:
    cid = _resolve_cluster_id(cluster_id)
    key = f"pve:{cid}:cluster_status"

    async def _produce() -> list[dict]:
        try:
            pve = get_pve(cluster_id)
            return await asyncio.to_thread(pve.get_cluster_status)
        except NoClustersConfigured:
            return []
        except Exception as exc:
            logger.warning("get_cluster_status(%s) failed: %s", cid, exc)
            return []

    return await cached_call(key, CLUSTER_STATUS_TTL, _produce)


async def get_vm_templates(cluster_id: str | None = None) -> list[dict]:
    cid = _resolve_cluster_id(cluster_id)
    key = f"pve:{cid}:templates"

    async def _produce() -> list[dict]:
        try:
            pve = get_pve(cluster_id)
            return await asyncio.to_thread(pve.get_vm_templates)
        except NoClustersConfigured:
            return []
        except Exception as exc:
            logger.warning("get_vm_templates(%s) failed: %s", cid, exc)
            return []

    return await cached_call(key, TEMPLATES_TTL, _produce)


async def get_storage_list(cluster_id: str | None = None) -> list[dict]:
    cid = _resolve_cluster_id(cluster_id)
    key = f"pve:{cid}:storage_list"

    async def _produce() -> list[dict]:
        try:
            pve = get_pve(cluster_id)
            return await asyncio.to_thread(pve.get_storage_list)
        except NoClustersConfigured:
            return []
        except Exception as exc:
            logger.warning("get_storage_list(%s) failed: %s", cid, exc)
            return []

    return await cached_call(key, STORAGE_LIST_TTL, _produce)


async def get_sdn_zones(cluster_id: str | None = None) -> list[dict]:
    cid = _resolve_cluster_id(cluster_id)
    key = f"pve:{cid}:sdn_zones"

    async def _produce() -> list[dict]:
        try:
            pve = get_pve(cluster_id)
            return await asyncio.to_thread(pve.get_sdn_zones)
        except NoClustersConfigured:
            return []
        except Exception as exc:
            logger.warning("get_sdn_zones(%s) failed: %s", cid, exc)
            return []

    return await cached_call(key, SDN_ZONES_TTL, _produce)


async def get_sdn_vnets(cluster_id: str | None = None) -> list[dict]:
    cid = _resolve_cluster_id(cluster_id)
    key = f"pve:{cid}:sdn_vnets"

    async def _produce() -> list[dict]:
        try:
            pve = get_pve(cluster_id)
            return await asyncio.to_thread(pve.get_sdn_vnets)
        except NoClustersConfigured:
            return []
        except Exception as exc:
            logger.warning("get_sdn_vnets(%s) failed: %s", cid, exc)
            return []

    return await cached_call(key, SDN_VNETS_TTL, _produce)


async def call_async(fn, *args: Any, **kwargs: Any) -> Any:
    """Generic ``asyncio.to_thread`` wrapper for ad-hoc proxmoxer calls.

    Use this for write/mutating calls that should not be cached but still
    must not block the event loop, e.g. ``await call_async(pve.create_sdn_vnet, name, zone)``.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)
