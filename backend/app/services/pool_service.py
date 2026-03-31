"""Proxmox pool lifecycle - one pool per PAWS user for cluster-side management."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Resource, User
from app.services.proxmox_client import get_pve

logger = logging.getLogger(__name__)


async def ensure_user_pool(db: AsyncSession, user: User, cluster_id: str | None = None) -> str | None:
    """Create the user's Proxmox pool if it doesn't exist. Returns pool name."""
    pve = get_pve(cluster_id)
    pool_name = pve.get_pool_name_for_user(user.username)
    try:
        if not pve.pool_exists(pool_name):
            pve.create_pool(pool_name, comment=f"PAWS user: {user.username}")
            logger.info("Created Proxmox pool %s for user %s", pool_name, user.username)
        return pool_name
    except Exception as e:
        logger.warning("Failed to create pool %s: %s", pool_name, e)
        return None


async def add_resource_to_pool(db: AsyncSession, user: User, vmid: int, cluster_id: str | None = None) -> None:
    """Add a VM/container to the user's pool after creation."""
    pve = get_pve(cluster_id)
    pool_name = pve.get_pool_name_for_user(user.username)
    try:
        pve.add_to_pool(pool_name, vmid)
    except Exception as e:
        logger.warning("Failed to add VMID %d to pool %s: %s", vmid, pool_name, e)


async def cleanup_user_pool(db: AsyncSession, user: User, cluster_id: str | None = None) -> None:
    """Delete the user's Proxmox pool if they have no remaining resources."""
    count_result = await db.execute(
        select(func.count(Resource.id)).where(
            Resource.owner_id == user.id,
            Resource.resource_type.in_(("vm", "lxc")),
        )
    )
    remaining = count_result.scalar() or 0
    if remaining > 0:
        return

    pve = get_pve(cluster_id)
    pool_name = pve.get_pool_name_for_user(user.username)
    try:
        if pve.pool_exists(pool_name):
            pve.delete_pool(pool_name)
            logger.info("Deleted empty pool %s for user %s", pool_name, user.username)
    except Exception as e:
        logger.warning("Failed to delete pool %s: %s", pool_name, e)
