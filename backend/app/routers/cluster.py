"""User-facing cluster health endpoint - sanitized, no raw capacity numbers."""

import logging

from fastapi import APIRouter, Depends

from app.core.deps import get_current_active_user
from app.models.models import User
from app.schemas.schemas import ClusterNodeStatus, ClusterStatusResponse
from app.services.proxmox_client import proxmox_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cluster", tags=["cluster"])


@router.get("/status", response_model=ClusterStatusResponse)
async def cluster_health(_: User = Depends(get_current_active_user)):
    """Sanitized cluster health for all authenticated users.

    Shows node count, per-node online/offline status, and API connectivity.
    Does NOT expose raw CPU/RAM/disk capacity to prevent users seeing total resources.
    """
    try:
        nodes = proxmox_client.get_nodes()
        cluster_info = proxmox_client.get_cluster_status()
    except Exception:
        logger.warning("Proxmox API unreachable for cluster health check")
        return ClusterStatusResponse(api_reachable=False)

    cluster_name = None
    quorate = False
    for item in cluster_info:
        if item.get("type") == "cluster":
            cluster_name = item.get("name")
            quorate = bool(item.get("quorate", 0))
            break

    node_statuses = [
        ClusterNodeStatus(
            name=n.get("node", "unknown"),
            status="online" if n.get("status") == "online" else "offline",
            uptime_seconds=n.get("uptime", 0),
        )
        for n in nodes
    ]

    return ClusterStatusResponse(
        api_reachable=True,
        cluster_name=cluster_name,
        node_count=len(node_statuses),
        nodes_online=sum(1 for n in node_statuses if n.status == "online"),
        nodes=node_statuses,
        quorate=quorate,
    )
