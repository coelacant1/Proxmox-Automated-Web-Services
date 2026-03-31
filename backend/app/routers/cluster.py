"""User-facing cluster health endpoint - sanitized, no raw capacity numbers."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import Resource, User
from app.schemas.schemas import ClusterNodeStatus, ClusterStatusResponse
from app.services.cluster_registry import cluster_registry
from app.services.proxmox_client import get_pve

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cluster", tags=["cluster"])


@router.get("/list")
async def list_available_clusters(_: User = Depends(get_current_active_user)) -> list[dict[str, Any]]:
    """List available clusters (name only, no credentials)."""
    return [{"name": cid} for cid in cluster_registry.list_cluster_ids()]


@router.get("/status", response_model=ClusterStatusResponse)
async def cluster_health(
    _: User = Depends(get_current_active_user),
    cluster_id: str | None = Query(None, description="Target cluster (omit for default)"),
):
    """Sanitized cluster health for all authenticated users.

    Shows node count, per-node online/offline status, and API connectivity.
    Does NOT expose raw CPU/RAM/disk capacity to prevent users seeing total resources.
    """
    pve = get_pve(cluster_id)
    try:
        nodes = pve.get_nodes()
        cluster_info = pve.get_cluster_status()
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


def _parse_upid(upid: str) -> dict:
    """Parse a Proxmox UPID string into components.

    Format: UPID:node:pid:pstart:starttime:type:id:user@realm:
    """
    parts = upid.split(":")
    if len(parts) < 8:
        return {}
    return {
        "node": parts[1],
        "pid": parts[2],
        "starttime": parts[4],
        "task_type": parts[5],
        "vmid": parts[6] if parts[6] else None,
        "pve_user": parts[7] if len(parts) > 7 else None,
    }


# Friendly names for Proxmox task types
_TASK_TYPE_LABELS = {
    "qmstart": "VM Start",
    "qmstop": "VM Stop",
    "qmshutdown": "VM Shutdown",
    "qmreboot": "VM Reboot",
    "qmsuspend": "VM Suspend",
    "qmresume": "VM Resume",
    "qmcreate": "VM Create",
    "qmdestroy": "VM Destroy",
    "qmclone": "VM Clone",
    "qmmigrate": "VM Migrate",
    "qmconfig": "VM Config",
    "qmresize": "VM Resize Disk",
    "qmrollback": "VM Rollback Snapshot",
    "qmsnapshot": "VM Snapshot",
    "qmdelsnapshot": "VM Delete Snapshot",
    "qmtemplate": "VM Convert to Template",
    "qmmonitor": "VM Monitor",
    "vzcreate": "CT Create",
    "vzdestroy": "CT Destroy",
    "vzstart": "CT Start",
    "vzstop": "CT Stop",
    "vzshutdown": "CT Shutdown",
    "vzreboot": "CT Reboot",
    "vzmigrate": "CT Migrate",
    "vzclone": "CT Clone",
    "vzsnapshot": "CT Snapshot",
    "vzdelsnapshot": "CT Delete Snapshot",
    "vzrollback": "CT Rollback Snapshot",
    "vzresize": "CT Resize Disk",
    "vzmount": "CT Mount",
    "vzumount": "CT Unmount",
    "imgcopy": "Disk Image Copy",
    "imgdel": "Disk Image Delete",
    "download": "Download",
    "vzdump": "Backup",
    "qmrestore": "VM Restore",
    "vzrestore": "CT Restore",
    "move_disk": "Move Disk",
    "ha-manager": "HA Manager",
    "startall": "Start All",
    "stopall": "Stop All",
    "migrateall": "Migrate All",
    "aptupdate": "APT Update",
    "aptupgrade": "APT Upgrade",
    "srvreload": "Service Reload",
    "srvrestart": "Service Restart",
    "srvstart": "Service Start",
    "srvstop": "Service Stop",
}


@router.get("/admin/tasks")
async def admin_cluster_tasks(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
    limit: int = Query(100, ge=1, le=500),
    node: str | None = Query(None),
    vmid: int | None = Query(None),
    type_filter: str | None = Query(None, alias="type"),
    since: int | None = Query(None, description="Unix epoch -- only tasks started after this time"),
    errors_only: bool = Query(False),
    cluster_id: str | None = Query(None, description="Target cluster (omit for default)"),
):
    """Full PVE cluster task history with PAWS user attribution.

    Fetches tasks from all (or one) node, cross-references VMIDs with PAWS
    Resource records to show which PAWS user owns the affected resource.
    """
    try:
        pve = get_pve(cluster_id)
        nodes_list = pve.get_nodes()
    except Exception:
        return {"tasks": [], "error": "Proxmox API unreachable"}

    target_nodes = [node] if node else [n["node"] for n in nodes_list if n.get("status") == "online"]

    # Build VMID -> PAWS resource/user lookup
    result = await db.execute(select(Resource).where(Resource.proxmox_vmid.isnot(None)))
    resources = result.scalars().all()
    vmid_map: dict[int, dict] = {}
    owner_ids = set()
    for r in resources:
        vmid_map[r.proxmox_vmid] = {
            "resource_id": str(r.id),
            "display_name": r.display_name,
            "resource_type": r.resource_type,
            "owner_id": str(r.owner_id),
        }
        owner_ids.add(r.owner_id)

    # Pre-fetch user info for all resource owners
    user_map: dict[str, dict] = {}
    if owner_ids:
        user_result = await db.execute(select(User).where(User.id.in_(owner_ids)))
        for u in user_result.scalars().all():
            user_map[str(u.id)] = {"username": u.username, "email": u.email}

    # Fetch tasks from PVE nodes
    all_tasks = []
    for n in target_nodes:
        try:
            params: dict = {"limit": limit}
            if vmid:
                params["vmid"] = vmid
            if type_filter:
                params["typefilter"] = type_filter
            if since:
                params["since"] = since
            if errors_only:
                params["errors"] = 1

            tasks = pve.api.nodes(n).tasks.get(**params)
            for t in tasks:
                t["_source_node"] = n
            all_tasks.extend(tasks)
        except Exception as e:
            logger.warning("Failed to fetch tasks from node %s: %s", n, e)

    # Sort by starttime descending (most recent first)
    all_tasks.sort(key=lambda t: t.get("starttime", 0), reverse=True)
    all_tasks = all_tasks[:limit]

    # Enrich with PAWS user attribution
    enriched = []
    for t in all_tasks:
        task_vmid_str = str(t.get("id", ""))
        task_vmid = int(task_vmid_str) if task_vmid_str.isdigit() else None
        task_type = t.get("type", "")

        paws_info = None
        if task_vmid and task_vmid in vmid_map:
            res = vmid_map[task_vmid]
            owner = user_map.get(res["owner_id"], {})
            paws_info = {
                "resource_id": res["resource_id"],
                "display_name": res["display_name"],
                "resource_type": res["resource_type"],
                "owner_username": owner.get("username"),
                "owner_email": owner.get("email"),
            }

        start_ts = t.get("starttime", 0)
        end_ts = t.get("endtime")
        duration = (end_ts - start_ts) if end_ts and start_ts else None

        enriched.append(
            {
                "upid": t.get("upid", ""),
                "node": t.get("node", t.get("_source_node", "")),
                "vmid": task_vmid,
                "type": task_type,
                "type_label": _TASK_TYPE_LABELS.get(task_type, task_type),
                "status": t.get("status", ""),
                "pve_user": t.get("user", ""),
                "starttime": start_ts,
                "endtime": end_ts,
                "duration_seconds": duration,
                "start_iso": datetime.fromtimestamp(start_ts, tz=UTC).isoformat() if start_ts else None,
                "end_iso": datetime.fromtimestamp(end_ts, tz=UTC).isoformat() if end_ts else None,
                "paws": paws_info,
            }
        )

    return {"tasks": enriched, "total": len(enriched)}


@router.get("/admin/tasks/{node}/{upid:path}")
async def admin_task_detail(
    node: str,
    upid: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
    cluster_id: str | None = Query(None, description="Target cluster (omit for default)"),
):
    """Get full detail and log output for a single PVE task."""
    try:
        pve = get_pve(cluster_id)
        status = pve.get_task_status(node, upid)
    except Exception as e:
        return {"error": f"Failed to fetch task status: {e}"}

    try:
        log_lines = pve.get_task_log(node, upid, limit=5000)
    except Exception:
        log_lines = []

    # Build log text from line dicts
    log_text = "\n".join(line.get("t", "") for line in sorted(log_lines, key=lambda entry: entry.get("n", 0)))

    # PAWS attribution
    parsed = _parse_upid(upid)
    task_vmid = int(parsed.get("vmid")) if parsed.get("vmid", "").isdigit() else None
    paws_info = None
    if task_vmid:
        result = await db.execute(select(Resource).where(Resource.proxmox_vmid == task_vmid))
        res = result.scalar_one_or_none()
        if res:
            user_result = await db.execute(select(User).where(User.id == res.owner_id))
            owner = user_result.scalar_one_or_none()
            paws_info = {
                "resource_id": str(res.id),
                "display_name": res.display_name,
                "resource_type": res.resource_type,
                "owner_username": owner.username if owner else None,
                "owner_email": owner.email if owner else None,
            }

    start_ts = status.get("starttime", 0)
    end_ts = status.get("endtime")
    duration = (end_ts - start_ts) if end_ts and start_ts else None
    task_type = status.get("type", parsed.get("task_type", ""))

    return {
        "upid": upid,
        "node": node,
        "vmid": task_vmid,
        "type": task_type,
        "type_label": _TASK_TYPE_LABELS.get(task_type, task_type),
        "status": status.get("status", ""),
        "exitstatus": status.get("exitstatus", ""),
        "pve_user": status.get("user", parsed.get("pve_user", "")),
        "starttime": start_ts,
        "endtime": end_ts,
        "duration_seconds": duration,
        "start_iso": datetime.fromtimestamp(start_ts, tz=UTC).isoformat() if start_ts else None,
        "end_iso": datetime.fromtimestamp(end_ts, tz=UTC).isoformat() if end_ts else None,
        "log": log_text,
        "paws": paws_info,
    }
