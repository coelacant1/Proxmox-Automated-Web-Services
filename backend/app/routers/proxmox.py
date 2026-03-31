"""Proxmox cluster status endpoints (admin + user overview)."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_current_active_user, require_admin
from app.models.models import User
from app.services.node_service import get_node_resources
from app.services.proxmox_client import get_pve

router = APIRouter(prefix="/api/proxmox", tags=["proxmox"])


@router.get("/nodes")
async def list_nodes(_: User = Depends(require_admin)):
    """Get cluster node status (admin only)."""
    try:
        return get_node_resources()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Proxmox: {e}")


@router.get("/cluster/status")
async def cluster_status(
    cluster_id: str | None = Query(None, description="Target cluster"),
    _: User = Depends(require_admin),
):
    """Get cluster-level status (admin only)."""
    try:
        return get_pve(cluster_id).get_cluster_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Proxmox: {e}")


@router.get("/templates")
async def list_templates(
    cluster_id: str | None = Query(None, description="Target cluster"),
    _: User = Depends(get_current_active_user),
):
    """List available VM templates."""
    try:
        return get_pve(cluster_id).get_vm_templates()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Proxmox: {e}")


@router.get("/storage")
async def list_storage(
    cluster_id: str | None = Query(None, description="Target cluster"),
    _: User = Depends(require_admin),
):
    """List storage pools (admin only)."""
    try:
        return get_pve(cluster_id).get_storage_list()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Proxmox: {e}")
