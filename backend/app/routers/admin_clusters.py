"""Admin endpoints for cluster management.

Clusters are configured via the Admin UI (Infrastructure > Connections) and
stored (encrypted) in the ``cluster_connections`` table. These endpoints
provide read-only visibility and health status for every registered cluster.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.core.deps import require_admin
from app.models.models import User
from app.services.cluster_registry import cluster_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/clusters", tags=["admin-clusters"])


@router.get("/", dependencies=[Depends(require_admin)])
async def list_clusters(current_user: User = Depends(require_admin)) -> list[dict[str, Any]]:
    """List all configured Proxmox clusters with connectivity status."""
    results = []
    for cid in cluster_registry.list_cluster_ids():
        cfg = cluster_registry.get_config(cid)
        pve = cluster_registry.get_pve(cid)
        try:
            pbs = cluster_registry.get_pbs(cid)
        except KeyError:
            pbs = None

        cluster_info: dict[str, Any] = {
            "name": cfg.name,
            "host": cfg.host,
            "port": cfg.port,
            "pbs_host": cfg.pbs_host or None,
            "pbs_configured": bool(pbs and pbs.configured),
            "pve_connected": False,
            "pbs_connected": False,
            "nodes": [],
            "node_count": 0,
        }

        try:
            nodes = pve.get_nodes()
            cluster_info["pve_connected"] = True
            cluster_info["nodes"] = [n.get("node", "") for n in nodes]
            cluster_info["node_count"] = len(nodes)
        except Exception as exc:
            logger.warning("Failed to connect to cluster '%s': %s", cid, exc)

        if pbs and pbs.configured:
            try:
                await pbs.list_datastores()
                cluster_info["pbs_connected"] = True
            except Exception:
                pass

        results.append(cluster_info)
    return results


@router.get("/{cluster_id}/status", dependencies=[Depends(require_admin)])
async def get_cluster_status(
    cluster_id: str,
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Get detailed status for a specific cluster."""
    pve = cluster_registry.get_pve(cluster_id)
    try:
        cluster_status = pve.get_cluster_status()
        nodes = pve.get_nodes()
        return {
            "name": cluster_id,
            "connected": True,
            "cluster_info": cluster_status,
            "nodes": nodes,
        }
    except Exception as exc:
        return {
            "name": cluster_id,
            "connected": False,
            "error": str(exc),
            "cluster_info": [],
            "nodes": [],
        }
