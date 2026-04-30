"""Proxmox cluster status endpoints (admin + user overview)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_current_active_user, require_admin
from app.models.models import User
from app.services.node_service import get_node_resources
from app.services.proxmox_cache import get_cluster_status as cached_cluster_status
from app.services.proxmox_cache import get_storage_list as cached_storage_list
from app.services.proxmox_cache import get_vm_templates as cached_vm_templates

router = APIRouter(prefix="/api/proxmox", tags=["proxmox"])


@router.get("/nodes")
async def list_nodes(_: User = Depends(require_admin)):
    """Get cluster node status (admin only)."""
    try:
        return await asyncio.to_thread(get_node_resources)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Proxmox: {e}")


@router.get("/cluster/status")
async def cluster_status(
    cluster_id: str | None = Query(None, description="Target cluster"),
    _: User = Depends(require_admin),
):
    """Get cluster-level status (admin only)."""
    try:
        return await cached_cluster_status(cluster_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Proxmox: {e}")


@router.get("/templates")
async def list_templates(
    cluster_id: str | None = Query(None, description="Target cluster"),
    _: User = Depends(get_current_active_user),
):
    """List available VM templates."""
    try:
        return await cached_vm_templates(cluster_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Proxmox: {e}")


@router.get("/storage")
async def list_storage(
    cluster_id: str | None = Query(None, description="Target cluster"),
    _: User = Depends(require_admin),
):
    """List storage pools (admin only)."""
    try:
        return await cached_storage_list(cluster_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Proxmox: {e}")
